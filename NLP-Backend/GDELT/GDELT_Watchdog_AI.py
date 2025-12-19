import requests
import pandas as pd
import pandas_gbq
from google.cloud import bigquery 
from datetime import datetime
import os
import logging
import json
import difflib
import sys

# --- CONFIGURATION ---
KEYWORDS = '("Tech Industry" OR "Tech Company" OR "Ecocide" OR "climate change" OR "disaster")'

# Region to search
TARGET_COUNTRY = ["US", "UK"]

# Similarity Threshold (0.0 to 1.0)
SIMILARITY_THRESHOLD = 0.85

# --- STORAGE CONFIGURATION ---
DATA_FILE = "./download/tech-tracker-cc-data.csv"

# BigQuery Settings
ENABLE_BIGQUERY = True # Ensure this is True
BQ_PROJECT_ID = "visible-truth-460414" #"gen-lang-client-0493347111"
# Format MUST be: dataset_name.table_name
BQ_DATASET_TABLE = "ai_companies_climate.articles" #"news_watchdog_cop30.articles" 
BQ_LOCATION = "europe-west4" 

# Credential setup -> Go to Google Cloud Console -> IAM & ADMIN -> Service Accounts -> Keys Tab -> Add Key -> JSON
SERVICE_ACCOUNT_JSON = "visible-truth-460414-cd878825e306.json" #"gen-lang-client-0493347111-e8dfa0685166.json"

if os.path.exists(SERVICE_ACCOUNT_JSON):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = SERVICE_ACCOUNT_JSON

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class GdeltWatchdog:
    def __init__(self, filepath):
        self.filepath = filepath
        self.base_url = "https://api.gdeltproject.org/api/v2/doc/doc"

    def build_query(self, keywords, country=None):
        query = keywords
        if country:
            if isinstance(country, list):
                country_filter = " OR ".join([f"sourcecountry:{c}" for c in country])
                query += f" ({country_filter})"
            else:
                query += f" sourcecountry:{country}"
        query += " sourcelang:eng"
        return query

    def fetch_articles(self, query):
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; NewsWatchdog/1.0)'}
        params = {
            'query': query,
            'mode': 'artlist',
            'maxrecords': 250,
            'timespan': '24h',
            'format': 'json',
            'sort': 'DateDesc'
        }

        try:
            logging.info(f"Querying GDELT with: {query}")
            response = requests.get(self.base_url, params=params, headers=headers, timeout=15)
            response.raise_for_status()
            try:
                data = response.json()
                return data.get('articles', [])
            except json.JSONDecodeError:
                logging.error("API returned invalid JSON.")
                return []
        except requests.exceptions.RequestException as e:
            logging.error(f"API Request Failed: {e}")
            return []

    def get_existing_data(self):
        if not os.path.exists(self.filepath):
            return set(), []
        try:
            if os.path.getsize(self.filepath) == 0:
                return set(), []
            df = pd.read_csv(self.filepath, usecols=['url', 'title'])
            existing_urls = set(df['url'].unique())
            existing_titles = df['title'].dropna().astype(str).tolist()
            return existing_urls, existing_titles
        except Exception as e:
            logging.critical(f"CRITICAL ERROR: Could not read local CSV. Error: {e}")
            sys.exit(1)

    def is_duplicate_title(self, new_title, existing_titles):
        if not new_title: return False
        if new_title in existing_titles: return True
        for existing in reversed(existing_titles):
            ratio = difflib.SequenceMatcher(None, new_title, existing).ratio()
            if ratio > SIMILARITY_THRESHOLD:
                logging.info(f"Skipping duplicate content: '{new_title}' ~ '{existing}' ({ratio:.2f})")
                return True
        return False

    def process_articles(self, articles):
        if not articles:
            return pd.DataFrame()

        existing_urls, existing_titles = self.get_existing_data()
        new_records = []
        skipped_count = 0

        logging.info(f"Processing {len(articles)} fetched articles against {len(existing_titles)} existing records...")

        for art in articles:
            url = art.get('url')
            title = art.get('title')

            if url in existing_urls or self.is_duplicate_title(title, existing_titles):
                skipped_count += 1
                continue

            existing_titles.append(title)
            existing_urls.add(url)

            record = {
                'title': title,
                'url': url,
                'url_mobile': art.get('url_mobile', ''),
                'social_image': art.get('socialimage', ''),
                'published_date': art.get('seendate'),
                'domain': art.get('domain'),
                'source_country': art.get('sourcecountry'),
                'language': art.get('language'),
                'scraped_status': 'pending', # <--- Key: It marks them as pending for your local script
                'full_text': '',
                'ingested_at': datetime.now().isoformat()
            }
            new_records.append(record)

        if skipped_count > 0:
            logging.info(f"Skipped {skipped_count} articles.")
            
        return pd.DataFrame(new_records)

    def save_to_csv(self, df):
        if df.empty: return
        write_header = not os.path.exists(self.filepath)
        try:
            df.to_csv(self.filepath, mode='a', header=write_header, index=False)
            logging.info(f"CSV: Saved {len(df)} new rows.")
        except Exception as e:
            logging.error(f"Failed to write to CSV: {e}")

    def ensure_dataset_exists(self):
        try:
            dataset_id = BQ_DATASET_TABLE.split('.')[0]
            full_dataset_id = f"{BQ_PROJECT_ID}.{dataset_id}"
            client = bigquery.Client(project=BQ_PROJECT_ID)
            dataset = bigquery.Dataset(full_dataset_id)
            dataset.location = BQ_LOCATION
            client.create_dataset(dataset, exists_ok=True, timeout=30)
        except Exception as e:
            logging.error(f"BigQuery Dataset Check Failed: {e}")
            raise

    def save_to_bigquery(self, df):
        if not ENABLE_BIGQUERY or df.empty: return
        try:
            self.ensure_dataset_exists()
            logging.info("BigQuery: Uploading rows...")
            pandas_gbq.to_gbq(df, destination_table=BQ_DATASET_TABLE, project_id=BQ_PROJECT_ID, if_exists='append')
            logging.info(f"BigQuery: Upload Success.")
        except Exception as e:
            logging.error(f"BigQuery Upload Failed: {e}")

    def run(self):
        query = self.build_query(KEYWORDS, TARGET_COUNTRY)
        articles = self.fetch_articles(query)
        df_new = self.process_articles(articles)
        
        if not df_new.empty:
            self.save_to_csv(df_new)
            self.save_to_bigquery(df_new)
        else:
            logging.info("No new unique articles found.")

if __name__ == "__main__":
    logging.info("--- Starting Daily GDELT Watchdog ---")
    bot = GdeltWatchdog(DATA_FILE)
    bot.run()
    logging.info("--- Run Complete ---")