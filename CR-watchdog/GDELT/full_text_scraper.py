import os
import time
import pandas as pd
import logging
from google.cloud import bigquery
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
BQ_PROJECT_ID = "visible-truth-460414"
# Format MUST be: dataset_name.table_name
BQ_DATASET_TABLE = "ai_companies_climate.articles" 
SERVICE_ACCOUNT_JSON = "visible-truth-460414-cd878825e306.json"

BQ_LOCATION = "europe-west4" 
# --- SETUP ---
if os.path.exists(SERVICE_ACCOUNT_JSON):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = SERVICE_ACCOUNT_JSON

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_pending_articles(client):
    """Fetches articles from BigQuery that haven't been scraped yet."""
    query = f"""
        SELECT url, title 
        FROM `{BQ_DATASET_TABLE}` 
        WHERE scraped_status = 'pending'
        LIMIT 50 -- Batch size to avoid crashing if there are thousands
    """
    logging.info("Fetching pending articles from BigQuery...")
    return client.query(query).to_dataframe()

def scrape_with_browser(df):
    """Uses Playwright (Headless Chrome) to scrape text."""
    logging.info(f"Starting browser to scrape {len(df)} articles...")
    
    texts = []
    statuses = []
    
    with sync_playwright() as p:
        # Launch Chrome. headless=True means invisible.
        # Set headless=False if you want to watch it work (cool for debugging!)
        browser = p.chromium.launch(headless=True)
        
        for index, row in df.iterrows():
            url = row['url']
            logging.info(f"Visiting: {url}")
            
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            try:
                # Go to page and wait up to 10s
                page.goto(url, timeout=10000, wait_until="domcontentloaded")
                
                # Extract text from <p> tags (heuristics)
                # You can improve this selector for specific sites
                content = page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('p'))
                        .map(p => p.innerText)
                        .join('\\n\\n');
                }""")
                
                if len(content) > 200:
                    texts.append(content)
                    statuses.append('scraped')
                else:
                    texts.append("")
                    statuses.append('too_short')
                    
            except Exception as e:
                logging.warning(f"Failed: {e}")
                texts.append("")
                statuses.append('failed')
            finally:
                page.close()
                context.close()
                
            time.sleep(1) # Polite pause
            
        browser.close()
        
    df['full_text'] = texts
    df['scraped_status'] = statuses
    return df

def update_bigquery(client, df):
    """
    Updates BigQuery using a MERGE statement.
    We upload the updates to a temp table, then merge, then delete temp.
    """
    if df.empty: return

    # 1. Upload to a temporary staging table
    dataset_id = BQ_DATASET_TABLE.split('.')[0]
    table_id = BQ_DATASET_TABLE.split('.')[1]
    staging_table_id = f"{dataset_id}.temp_staging_updates"
    
    logging.info("Uploading scraped data to staging table...")
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    job = client.load_table_from_dataframe(df, f"{BQ_PROJECT_ID}.{staging_table_id}", job_config=job_config)
    job.result() # Wait for upload
    
    # 2. Run SQL Merge
    logging.info("Merging updates into main table...")
    merge_query = f"""
        MERGE `{BQ_PROJECT_ID}.{BQ_DATASET_TABLE}` T
        USING `{BQ_PROJECT_ID}.{staging_table_id}` S
        ON T.url = S.url
        WHEN MATCHED THEN
          UPDATE SET 
            T.full_text = S.full_text,
            T.scraped_status = S.scraped_status
    """
    client.query(merge_query).result()
    
    logging.info("Update complete! Data merged.")

if __name__ == "__main__":
    client = bigquery.Client(project=BQ_PROJECT_ID)
    
    # Loop until no more pending articles (process in batches)
    while True:
        df_pending = get_pending_articles(client)
        
        if df_pending.empty:
            logging.info("No more pending articles found. All caught up!")
            break
            
        df_scraped = scrape_with_browser(df_pending)
        update_bigquery(client, df_scraped)
        
        logging.info("Batch complete. Checking for more...")
        time.sleep(2)