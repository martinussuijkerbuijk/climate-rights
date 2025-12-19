import os
import pandas as pd
import logging
import re
import argparse
from datetime import datetime
from typing import Optional, List, Dict, Any
from google.cloud import bigquery
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

# --- CONFIGURATION ---
BQ_PROJECT_ID = "visible-truth-460414"
BQ_DATASET = "shell_phillipines"
BQ_TABLE = f"{BQ_DATASET}.telegram"
BQ_LOCATION = "EU"
SERVICE_ACCOUNT_JSON = "visible-truth-460414-cd878825e306.json"

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class TelegramNewsScraper:
    def __init__(self):
        self.setup_credentials()
        self.client = bigquery.Client(project=BQ_PROJECT_ID)
        self.ensure_table_exists()

    def setup_credentials(self):
        if os.path.exists(SERVICE_ACCOUNT_JSON):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = SERVICE_ACCOUNT_JSON
        else:
            logging.warning(f"Service account file '{SERVICE_ACCOUNT_JSON}' not found.")

    def ensure_table_exists(self):
        """
        Creates the 'telegram' table in BigQuery if it doesn't exist.
        """
        # Ensure dataset exists first
        try:
            dataset = bigquery.Dataset(f"{BQ_PROJECT_ID}.{BQ_DATASET}")
            dataset.location = BQ_LOCATION
            self.client.create_dataset(dataset, exists_ok=True)
        except Exception as e:
            logging.error(f"Dataset creation check failed: {e}")

        # Define Schema
        schema = [
            bigquery.SchemaField("telegram_date", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("channel", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("keyword", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("telegram_message_text", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("telegram_link", "STRING", mode="NULLABLE", description="Link to the specific telegram post"),
            bigquery.SchemaField("extracted_news_url", "STRING", mode="NULLABLE", description="URL extracted from the message text"),
            bigquery.SchemaField("scraped_full_text", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("scraped_at", "TIMESTAMP", mode="NULLABLE")
        ]

        table_ref = f"{BQ_PROJECT_ID}.{BQ_TABLE}"
        try:
            table = bigquery.Table(table_ref, schema=schema)
            self.client.create_table(table, exists_ok=True)
            logging.info(f"Verified BigQuery table: {BQ_TABLE}")
        except Exception as e:
            logging.error(f"Table creation error: {e}")

    def extract_url_from_text(self, text: str) -> Optional[str]:
        """
        Finds the first http/https URL in a string.
        """
        if not isinstance(text, str):
            return None
        
        # Regex to find URLs starting with http/https
        # It looks for http(s):// followed by non-whitespace characters
        url_pattern = r"(https?://\S+)"
        match = re.search(url_pattern, text)
        
        if match:
            url = match.group(1)
            # Cleanup trailing punctuation sometimes caught by regex (like a closing parenthesis or comma)
            return url.rstrip("),.]")
        return None

    def scrape_url(self, url: str) -> Optional[str]:
        """
        Scrapes full text using Playwright (Reused logic).
        """
        logging.info(f"Scraping: {url}")
        content = ""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(user_agent="Mozilla/5.0 (compatible; TelegramScraper/1.0)")
                page = context.new_page()
                
                # Timeout set to 30s to handle slow news sites
                page.goto(url, timeout=30000, wait_until="domcontentloaded")
                
                content = page.evaluate("""() => {
                    const article = document.querySelector('article');
                    if (article) return article.innerText;
                    
                    const main = document.querySelector('[role="main"]');
                    if (main) return main.innerText;
                    
                    // Fallback to paragraphs
                    return Array.from(document.querySelectorAll('p'))
                        .map(p => p.innerText)
                        .filter(t => t.length > 50)
                        .join('\\n\\n');
                }""")
                browser.close()
                
                if len(content) < 100:
                    logging.warning("Content too short, possibly failed scrape.")
                    return None
                return content

        except Exception as e:
            logging.error(f"Failed to scrape {url}: {e}")
            return None

    def save_batch_to_bigquery(self, rows: List[Dict[str, Any]]):
        """
        Inserts a list of rows into BigQuery.
        """
        if not rows:
            return

        try:
            errors = self.client.insert_rows_json(BQ_TABLE, rows)
            if not errors:
                logging.info(f"Successfully inserted {len(rows)} rows into {BQ_TABLE}.")
            else:
                logging.error(f"BigQuery Insertion Errors: {errors}")
        except Exception as e:
            logging.error(f"Failed to insert rows: {e}")

    def process_csv(self, file_path: str):
        """
        Main processing loop.
        """
        if not os.path.exists(file_path):
            logging.error(f"File not found: {file_path}")
            return

        logging.info(f"Reading CSV: {file_path}")
        try:
            df = pd.read_csv(file_path)
        except Exception as e:
            logging.error(f"Failed to read CSV: {e}")
            return

        # Prepare batch list
        rows_to_insert = []
        batch_size = 10 

        total_rows = len(df)
        logging.info(f"Found {total_rows} messages to process.")

        for index, row in df.iterrows():
            message_text = row.get("Message Text", "")
            
            # 1. Extract URL
            news_url = self.extract_url_from_text(message_text)
            
            scraped_text = None
            scraped_timestamp = None

            # 2. Scrape if URL exists
            if news_url:
                scraped_text = self.scrape_url(news_url)
                if scraped_text:
                    scraped_timestamp = datetime.now().isoformat()
            else:
                logging.debug("No extracted URL in message.")

            # 3. Prepare BQ Row
            # Parsing date safely
            try:
                date_str = row.get("Date")
                # Ensure date is compatible with BQ TIMESTAMP (ISO format)
                if date_str:
                    msg_date = pd.to_datetime(date_str).isoformat()
                else:
                    msg_date = None
            except:
                msg_date = None

            bq_row = {
                "telegram_date": msg_date,
                "channel": str(row.get("Channel", "")),
                "keyword": str(row.get("Keyword", "")),
                "telegram_message_text": str(message_text),
                "telegram_link": str(row.get("Link", "")), # This is the t.me link
                "extracted_news_url": news_url,
                "scraped_full_text": scraped_text,
                "scraped_at": scraped_timestamp
            }
            
            rows_to_insert.append(bq_row)

            # 4. Insert in batches
            if len(rows_to_insert) >= batch_size:
                self.save_batch_to_bigquery(rows_to_insert)
                rows_to_insert = []

        # Insert remaining
        if rows_to_insert:
            self.save_batch_to_bigquery(rows_to_insert)

        logging.info("CSV Processing Complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Telegram CSV Scraper & BQ Loader")
    parser.add_argument("--file", default="investigative_results_2025-12-15.csv", help="Path to the Telegram CSV file")
    
    args = parser.parse_args()
    
    scraper = TelegramNewsScraper()
    scraper.process_csv(args.file)