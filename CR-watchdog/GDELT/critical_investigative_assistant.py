import os
import json
import time
import logging
import re
import requests
import argparse
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from google.cloud import bigquery
from playwright.sync_api import sync_playwright
import google.generativeai as genai
from dotenv import load_dotenv


# --- CONFIGURATION ---
# BigQuery Settings
BQ_PROJECT_ID = "visible-truth-460414"
BQ_DATASET = "shell_phillipines" # Updated based on your query, change as needed
BQ_INVESTIGATIONS_TABLE = f"{BQ_DATASET}.investigations"
BQ_LOCATION = "EU" # Added location preference (optional, defaults to US if removed)
SERVICE_ACCOUNT_JSON = "visible-truth-460414-cd878825e306.json"

load_dotenv()
# Gemini AI Settings
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
GEMINI_MODEL_NAME = "gemini-2.5-flash"

# GDELT Settings
GDELT_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class CriticalPipeline:
    def __init__(self):
        """
        Initializes BigQuery and Gemini clients.
        """
        self.setup_credentials()
        self.client = bigquery.Client(project=BQ_PROJECT_ID)
        self.ensure_investigation_table_exists()
        
        # Initialize Gemini
        try:
            if not GOOGLE_API_KEY:
                logging.warning("GOOGLE_API_KEY not found in env. Gemini calls will fail unless authenticated.")
            genai.configure(api_key=GOOGLE_API_KEY)
            self.model = genai.GenerativeModel(GEMINI_MODEL_NAME)
            logging.info(f"Gemini Model '{GEMINI_MODEL_NAME}' initialized.")
        except Exception as e:
            logging.critical(f"Failed to initialize Gemini: {e}")
            raise

    def setup_credentials(self):
        if os.path.exists(SERVICE_ACCOUNT_JSON):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = SERVICE_ACCOUNT_JSON
        else:
            logging.warning(f"Service account file '{SERVICE_ACCOUNT_JSON}' not found.")

    def ensure_investigation_table_exists(self):
        """
        Ensures the BigQuery Dataset AND Table exist.
        Now explicitly uses BQ_LOCATION to prevent 404/Not Found errors due to location mismatch.
        """
        # 1. Ensure Dataset Exists
        dataset_id = f"{BQ_PROJECT_ID}.{BQ_DATASET}"
        try:
            # Construct a full Dataset object to specify location
            dataset = bigquery.Dataset(dataset_id)
            dataset.location = BQ_LOCATION
            self.client.create_dataset(dataset, exists_ok=True)
            logging.info(f"Verified BigQuery dataset: {BQ_DATASET} in location {BQ_LOCATION}")
        except Exception as e:
            logging.critical(f"CRITICAL: Failed to create/verify dataset '{BQ_DATASET}': {e}")
            raise # Stop execution if we can't create the dataset

        # 2. Ensure Table Exists
        schema = [
            bigquery.SchemaField("monitor_topic", "STRING", mode="NULLABLE", description="The specific case/topic being watched"),
            bigquery.SchemaField("url", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("analysis_timestamp", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("case_status", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("core_issue", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("hypocrisy_risk", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("actors", "RECORD", mode="REPEATED", fields=[
                bigquery.SchemaField("name", "STRING"),
                bigquery.SchemaField("role", "STRING"), # Instigator, Resister, Enforcer
                bigquery.SchemaField("type", "STRING")  # Corporation, NGO, Court, Govt
            ]),
            bigquery.SchemaField("evidence_leads", "STRING", mode="REPEATED"),
            bigquery.SchemaField("evidence_urls", "STRING", mode="REPEATED"),
        ]
        
        table_ref = f"{BQ_PROJECT_ID}.{BQ_INVESTIGATIONS_TABLE}"
        try:
            table = bigquery.Table(table_ref, schema=schema)
            self.client.create_table(table, exists_ok=True)
            logging.info(f"Verified BigQuery table: {BQ_INVESTIGATIONS_TABLE}")
        except Exception as e:
            logging.critical(f"CRITICAL: BigQuery Table Creation Error: {e}")
            raise # Stop execution if we can't create the table

    # --- WATCHDOG: SEARCH & DEDUPLICATION ---

    def search_gdelt(self, keywords: str, timespan: str = "24h") -> List[Dict[str, str]]:
        """
        Queries GDELT for new articles matching the keywords.
        """
        logging.info(f"Watchdog: Searching GDELT for '{keywords}' over last {timespan}...")
        
        params = {
            'query': f"{keywords} sourcelang:eng",
            'mode': 'artlist',
            'maxrecords': 50, # Adjustable limit per run
            'timespan': timespan,
            'format': 'json',
            'sort': 'DateDesc'
        }
        
        try:
            response = requests.get(GDELT_BASE_URL, params=params, timeout=20)
            response.raise_for_status()
            data = response.json()
            articles = data.get('articles', [])
            logging.info(f"Watchdog: Found {len(articles)} raw articles.")
            return articles
        except Exception as e:
            logging.error(f"GDELT Search failed: {e}")
            return []

    def check_if_url_exists(self, url: str) -> bool:
        """
        Checks BigQuery to see if we have already investigated this URL.
        Prevents double-spending on LLM costs and duplicate data.
        """
        query = f"""
            SELECT COUNT(*) as count 
            FROM `{BQ_PROJECT_ID}.{BQ_INVESTIGATIONS_TABLE}` 
            WHERE url = @url
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("url", "STRING", url)]
        )
        
        try:
            results = self.client.query(query, job_config=job_config).result()
            for row in results:
                return row.count > 0
        except Exception as e:
            # If table doesn't exist yet, it's not a duplicate
            logging.warning(f"Deduplication check failed (ignoring): {e}")
            return False
        return False

    # --- NODE 1: SCRAPING (Playwright) ---
    
    def scrape_url(self, url: str) -> Optional[str]:
        """
        Uses Playwright to scrape full text.
        """
        logging.info(f"Node 1: Scraping target: {url}")
        content = ""
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            try:
                page.goto(url, timeout=20000, wait_until="domcontentloaded")
                
                content = page.evaluate("""() => {
                    const article = document.querySelector('article');
                    if (article) return article.innerText;
                    
                    const main = document.querySelector('[role="main"]');
                    if (main) return main.innerText;
                    
                    return Array.from(document.querySelectorAll('p'))
                        .map(p => p.innerText)
                        .filter(t => t.length > 50)
                        .join('\\n\\n');
                }""")
                
                if not content or len(content) < 300:
                    logging.warning("Scraped content seems too short or empty.")
                    content = None
                else:
                    logging.info(f"Successfully scraped {len(content)} chars.")
                    
            except Exception as e:
                logging.error(f"Scraping failed: {e}")
                content = None
            finally:
                browser.close()
                
        return content

    # --- NODE 1.5: GEMINI ANALYSIS ---

    def analyze_topology(self, text: str, url: str, monitor_topic: str) -> Dict[str, Any]:
        """
        Uses Gemini 2.5 Flash to extract critical topology from the text.
        """
        logging.info("Node 1.5: Sending text to Gemini for Critical Topology extraction...")
        
        clean_text = text[:15000]

        prompt = f"""
        You are a Critical Legal Investigator watching the topic: "{monitor_topic}".
        Analyze the following news text.
        
        Your Goal: Extract the 'Conflict Topology'.
        
        Input Text:
        "{clean_text}" 
        
        Instructions:
        1. Determine the 'case_status': Is it 'Active Litigation', 'Pre-Litigation', 'Post-Judgment', or 'Irrelevant'?
        2. Identify 'actors': List key entities (Corps, NGOs, Gov, Courts). Assign roles (Instigator, Resister, Enforcer).
        3. Identify 'core_issue': The central legal/moral conflict.
        4. Assess 'hypocrisy_risk': Contradictions between public pledges and actions.
        
        Output purely valid JSON:
        {{
            "case_status": "string",
            "core_issue": "string",
            "hypocrisy_risk": "string",
            "actors": [
                {{"name": "string", "role": "string", "type": "string"}}
            ]
        }}
        """

        try:
            response = self.model.generate_content(prompt)
            json_str = response.text
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0]
            json_str = json_str.strip()
                
            analysis = json.loads(json_str)
            analysis['url'] = url
            analysis['analysis_timestamp'] = datetime.now().isoformat()
            
            logging.info(f"Gemini Analysis Complete. Status: {analysis.get('case_status')}")
            return analysis
            
        except Exception as e:
            logging.error(f"Gemini Analysis Failed: {e}")
            return {
                "url": url,
                "analysis_timestamp": datetime.now().isoformat(),
                "case_status": "Analysis Error",
                "core_issue": str(e),
                "hypocrisy_risk": "Unknown",
                "actors": []
            }

    # --- NODE 2: EVIDENCE STRATEGIST (FORENSIC LLM LAYER) ---

    def generate_evidence_leads(self, text: str, topology: Dict[str, Any]) -> List[str]:
        """
        Uses LLM to generate creative, deep-dive search queries based on the full text.
        """
        logging.info("Node 2: Sending text to LLM for Forensic Search Strategy generation...")
        
        clean_text = text[:15000]
        actors_str = ", ".join([f"{a['name']} ({a['role']})" for a in topology.get('actors', [])])
        case_status = topology.get('case_status', 'Unknown')
        
        prompt = f"""
        You are an expert Forensic Investigator and Open Source Intelligence (OSINT) specialist.
        
        Target Case Status: {case_status}
        Identified Actors: {actors_str}
        
        Article Text:
        "{clean_text}"
        
        Your Mission:
        Devise a 'Deep Dive' search strategy to build a case.
        CRITICAL INSTRUCTION: Avoid overly complex queries that yield 0 results. 
        Create a mix of BROAD searches (to find the site) and SPECIFIC searches (to find the doc).
        
        Generate 10 Advanced Google Search Operators (Dorks) across these categories:
        1. Financials: 'annual report', '10-k', 'tax return'
        2. Legal/Court: 'docket', 'complaint', 'judgment', 'v.'
        3. Regulatory: 'violation', 'fine', 'permit', 'notice'
        4. Forensics: 'confidential', 'draft', 'internal' (filetype:pdf)
        
        Output format: A JSON object containing a single list called "leads".
        Example: {{ "leads": ["site:shell.com filetype:pdf 'sustainability'", "intitle:'index of' climate"] }}
        """

        try:
            response = self.model.generate_content(prompt)
            json_str = response.text
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0]
            json_str = json_str.strip()
            
            data = json.loads(json_str)
            leads = data.get("leads", [])
            
            # Fallback if LLM returns empty
            if not leads:
                logging.warning("LLM returned no leads, using fallback...")
                leads = [f"site:courtlistener.com {actors_str}", f"filetype:pdf {actors_str} report"]
                
            logging.info(f"Generated {len(leads)} forensic leads.")
            
            # Update topology in place so it saves to BQ later
            topology['evidence_leads'] = leads
            return leads

        except Exception as e:
            logging.error(f"Forensic Strategy Generation Failed: {e}")
            fallback_leads = ["Error generating advanced leads. Check logs."]
            topology['evidence_leads'] = fallback_leads
            return fallback_leads

    # --- STORAGE ---

    def save_investigation(self, data: Dict[str, Any], monitor_topic: str):
        """
        Persists the full dossier to BigQuery.
        """
        logging.info(f"Saving to BigQuery: {BQ_INVESTIGATIONS_TABLE}...")
        
        leads = data.get('evidence_leads', [])
        # Generate actionable URLs from the leads
        evidence_urls = [f"https://www.google.com/search?q={urllib.parse.quote(lead)}" for lead in leads]

        row = {
            "monitor_topic": monitor_topic,
            "url": data['url'],
            "analysis_timestamp": data['analysis_timestamp'],
            "case_status": data.get('case_status'),
            "core_issue": data.get('core_issue'),
            "hypocrisy_risk": data.get('hypocrisy_risk'),
            "actors": data.get('actors', []),
            "evidence_leads": leads,
            "evidence_urls": evidence_urls # Storing the generated URLs
        }
        
        try:
            errors = self.client.insert_rows_json(BQ_INVESTIGATIONS_TABLE, [row])
            if not errors:
                logging.info("✅ Investigation saved successfully.")
            else:
                logging.error(f"❌ BigQuery Insert Errors: {errors}")
        except Exception as e:
            logging.error(f"❌ Failed to save to BigQuery: {e}")

    # --- EXECUTION MODES ---

    def print_actionable_dossier(self, topology: Dict[str, Any], leads: List[str]):
        """
        Prints the results with CLICKABLE links for immediate investigation.
        """
        print("\n--- 📝 INVESTIGATION DOSSIER ---")
        print(f"Status: {topology.get('case_status')}")
        print(f"Issue:  {topology.get('core_issue')}")
        print("\n[Forensic Search Plan - CLICK TO EXECUTE]")
        
        for lead in leads:
            # Encode the query for a valid URL
            encoded_query = urllib.parse.quote(lead)
            google_url = f"https://www.google.com/search?q={encoded_query}"
            
            # Print the clean link
            print(f"\n🔍 Query: {lead}")
            print(f"   👉 Link: {google_url}")

    def run_single_investigation(self, url: str, topic_name: str):
        """
        Mode 1: Investigate
        Deep dive into a single URL with Google Dorks generation.
        """
        print(f"\n--- 🕵️‍♂️ STARTING SINGLE INVESTIGATION: {url} ---")
        
        text = self.scrape_url(url)
        if text:
            topology = self.analyze_topology(text, url, topic_name)
            leads = self.generate_evidence_leads(text, topology)
            self.save_investigation(topology, topic_name)
            self.print_actionable_dossier(topology, leads)
            
        print("\n--- ✅ COMPLETE ---")

    def run_daily_watchdog(self, topic_name: str, search_keywords: str):
        """
        Mode 2: Watchdog
        Polls GDELT for new articles and processes them.
        """
        print(f"\n--- 🐕 STARTING WATCHDOG FOR: {topic_name} ---")
        
        articles = self.search_gdelt(search_keywords)
        if not articles:
            logging.info("No new articles found in GDELT.")
            return

        new_urls = []
        for art in articles:
            url = art.get('url')
            if url and not self.check_if_url_exists(url):
                new_urls.append(url)
            else:
                logging.debug(f"Skipping duplicate: {url}")
        
        logging.info(f"Found {len(new_urls)} new, unique URLs to investigate.")
        
        for i, url in enumerate(new_urls):
            print(f"\n--- Investigating [{i+1}/{len(new_urls)}]: {url} ---")
            
            text = self.scrape_url(url)
            if not text:
                continue

            topology = self.analyze_topology(text, url, topic_name)
            
            if topology.get('case_status') == 'Irrelevant':
                logging.info("Article deemed irrelevant. Skipping evidence generation.")
                self.save_investigation(topology, topic_name)
                continue

            leads = self.generate_evidence_leads(text, topology)
            self.save_investigation(topology, topic_name)
            self.print_actionable_dossier(topology, leads)
            
            time.sleep(2)

        print(f"\n--- ✅ WATCHDOG COMPLETE FOR {topic_name} ---")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Critical Investigative Assistant & Watchdog")
    parser.add_argument("--mode", choices=["watchdog", "investigate"], default="watchdog", help="Operation mode")
    parser.add_argument("--topic", default="General_Climate_Case", help="Topic/Case name for database tagging")
    parser.add_argument("--keywords", help="GDELT search keywords (required for watchdog)")
    parser.add_argument("--url", help="Target URL (required for investigate)")
    
    args = parser.parse_args()
    
    pipeline = CriticalPipeline()
    
    if args.mode == "watchdog":
        if not args.keywords:
            print("❌ Error: --keywords required for watchdog mode.")
        else:
            pipeline.run_daily_watchdog(args.topic, args.keywords)
            
    elif args.mode == "investigate":
        if not args.url:
            print("❌ Error: --url required for investigate mode.")
        else:
            pipeline.run_single_investigation(args.url, args.topic)