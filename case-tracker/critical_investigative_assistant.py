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

load_dotenv()

# --- CONFIGURATION ---
# BigQuery Settings
BQ_PROJECT_ID = os.environ.get("BQ_PROJECT_ID")
BQ_DATASET = os.environ.get("BQ_DATASET")
BQ_INVESTIGATIONS_TABLE = f"{BQ_DATASET}.investigations"
BQ_LOCATION = "EU" # Added location preference (optional, defaults to US if removed)
SERVICE_ACCOUNT_JSON = os.environ.get("SERVICE_ACCOUNT_JSON")


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
        """
        # 1. Ensure Dataset Exists
        dataset_id = f"{BQ_PROJECT_ID}.{BQ_DATASET}"
        try:
            dataset = bigquery.Dataset(dataset_id)
            dataset.location = BQ_LOCATION
            self.client.create_dataset(dataset, exists_ok=True)
            logging.info(f"Verified BigQuery dataset: {BQ_DATASET} in location {BQ_LOCATION}")
        except Exception as e:
            logging.critical(f"CRITICAL: Failed to create/verify dataset '{BQ_DATASET}': {e}")
            raise 

        # 2. Ensure Table Exists
        schema = [
            bigquery.SchemaField("monitor_topic", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("url", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("analysis_timestamp", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("case_status", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("core_issue", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("hypocrisy_risk", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("icj_compliance_check", "STRING", mode="NULLABLE", description="Assessment against ICJ 2025 Opinion"),
            bigquery.SchemaField("actors", "RECORD", mode="REPEATED", fields=[
                bigquery.SchemaField("name", "STRING"),
                bigquery.SchemaField("role", "STRING"), 
                bigquery.SchemaField("type", "STRING") 
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
            # Table might exist with old schema, handling that is complex, we assume compatible or new
            logging.warning(f"BigQuery Table Check/Create Warning: {e}")

    # --- WATCHDOG: SEARCH & DEDUPLICATION ---

    def search_gdelt(self, keywords: str, timespan: str = "24h") -> List[Dict[str, str]]:
        """
        Queries GDELT for new articles matching the keywords.
        """
        logging.info(f"Watchdog: Searching GDELT for '{keywords}' over last {timespan}...")
        
        params = {
            'query': f"{keywords} sourcelang:eng",
            'mode': 'artlist',
            'maxrecords': 50, 
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
        **UPDATED:** Now references the ICJ 2025 Advisory Opinion context.
        """
        logging.info("Node 1.5: Sending text to Gemini for Critical Topology extraction...")
        
        clean_text = text[:15000]

        # Injected Knowledge about ICJ Opinion
        icj_context = """
        LEGAL CONTEXT: The International Court of Justice (ICJ) issued an Advisory Opinion on July 23, 2025 (No. 2025/36). 
        It affirms that States have a binding obligation to prevent GHG emissions from causing significant harm to other States (especially Small Island Developing States).
        Companies and States failing to regulate them are now potentially liable under international law.
        """

        prompt = f"""
        You are a Critical Legal Investigator watching the topic: "{monitor_topic}".
        Analyze the following news text.
        
        {icj_context}
        
        Your Goal: Extract the 'Conflict Topology' and benchmark against the ICJ opinion.
        
        Input Text:
        "{clean_text}" 
        
        Instructions:
        1. Determine the 'case_status': Is it 'Active Litigation', 'Pre-Litigation', 'Post-Judgment', or 'Irrelevant'?
        2. Identify 'actors': List key entities (Corps, NGOs, Gov, Courts). Assign roles (Instigator, Resister, Enforcer).
        3. Identify 'core_issue': The central legal/moral conflict.
        4. Assess 'hypocrisy_risk': Contradictions between public pledges and actions.
        5. Assess 'icj_compliance_check': Does the Instigator's action potentially violate the 'Duty of Care' affirmed by the ICJ 2025 Opinion? (Yes/No/Partial - Explain briefly).
        
        Output purely valid JSON:
        {{
            "case_status": "string",
            "core_issue": "string",
            "hypocrisy_risk": "string",
            "icj_compliance_check": "string",
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
                "icj_compliance_check": "Unknown",
                "actors": []
            }

    # --- NODE 2: EVIDENCE STRATEGIST (FORENSIC LLM LAYER) ---

    def generate_evidence_leads(self, text: str, topology: Dict[str, Any]) -> List[str]:
        """
        Uses LLM to generate creative, deep-dive search queries.
        **UPDATED:** Now searches for links to the ICJ ruling in specific cases.
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
        Devise a 'Deep Dive' search strategy.
        Focus on finding links between these actors and the "ICJ July 2025 Advisory Opinion" on climate change.
        
        Generate 10 Advanced Google Search Operators (Dorks):
        1. Link to ICJ: "Company Name" AND "ICJ" AND "opinion", "Company Name" AND "duty of care"
        2. Financials: 'annual report', '10-k', 'tax return'
        3. Legal/Court: 'docket', 'complaint', 'judgment'
        4. Forensics: 'confidential', 'draft', 'internal' (filetype:pdf)
        
        Output format: A JSON object containing a single list called "leads".
        Example: {{ "leads": ["site:shell.com filetype:pdf 'ICJ'", "'Shell' 'Philippines' 'Odette' docket"] }}
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
            
            if not leads:
                logging.warning("LLM returned no leads, using fallback...")
                leads = [f"site:courtlistener.com {actors_str}", f"filetype:pdf {actors_str} ICJ"]
                
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
        evidence_urls = [f"https://www.google.com/search?q={urllib.parse.quote(lead)}" for lead in leads]

        row = {
            "monitor_topic": monitor_topic,
            "url": data['url'],
            "analysis_timestamp": data['analysis_timestamp'],
            "case_status": data.get('case_status'),
            "core_issue": data.get('core_issue'),
            "hypocrisy_risk": data.get('hypocrisy_risk'),
            "icj_compliance_check": data.get('icj_compliance_check'),
            "actors": data.get('actors', []),
            "evidence_leads": leads,
            "evidence_urls": evidence_urls
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
        Prints the results with CLICKABLE links.
        """
        print("\n--- 📝 INVESTIGATION DOSSIER ---")
        print(f"Status: {topology.get('case_status')}")
        print(f"Issue:  {topology.get('core_issue')}")
        print(f"ICJ Compliance: {topology.get('icj_compliance_check')}")
        print("\n[Forensic Search Plan - CLICK TO EXECUTE]")
        
        for lead in leads:
            encoded_query = urllib.parse.quote(lead)
            google_url = f"https://www.google.com/search?q={encoded_query}"
            print(f"\n🔍 Query: {lead}")
            print(f"   👉 Link: {google_url}")

    def run_single_investigation(self, url: str, topic_name: str):
        print(f"\n--- 🕵️‍♂️ STARTING SINGLE INVESTIGATION: {url} ---")
        
        text = self.scrape_url(url)
        if text:
            topology = self.analyze_topology(text, url, topic_name)
            leads = self.generate_evidence_leads(text, topology)
            self.save_investigation(topology, topic_name)
            self.print_actionable_dossier(topology, leads)
            
        print("\n--- ✅ COMPLETE ---")

    def run_daily_watchdog(self, topic_name: str, search_keywords: str):
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