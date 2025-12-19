import os
import sys
import argparse
import asyncio
import logging
from datetime import datetime, timedelta
import pandas as pd
from google.cloud import bigquery
import google.generativeai as genai
from telethon import TelegramClient, events
from telethon.tl.types import PeerChat, PeerChannel
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- CONFIGURATION ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL") 
GCP_PROJECT_ID = "gen-lang-client-0493347111" 
BQ_DATASET_TABLE = "news_watchdog_cop30.articles"

# Service Account Setup
SERVICE_ACCOUNT_JSON = "gen-lang-client-0493347111-e8dfa0685166.json"
if os.path.exists(SERVICE_ACCOUNT_JSON):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = SERVICE_ACCOUNT_JSON
else:
    logging.warning(f"Service account file '{SERVICE_ACCOUNT_JSON}' not found. BigQuery/Gemini might fail.")

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# --- GEMINI SETUP ---
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

async def send_telegram_message(message):
    """Sends a message to the Telegram channel."""
    if not TELEGRAM_BOT_TOKEN:
        logging.error("TELEGRAM_BOT_TOKEN not found in .env")
        return

    try:
        # We use the bot token to sign in
        client = TelegramClient('bot_session', TELEGRAM_API_ID, TELEGRAM_API_HASH)
        await client.start(bot_token=TELEGRAM_BOT_TOKEN)
        
        # Resolve channel entity
        # Note: If the bot is not an admin, it might fail to post if the channel is private.
        # If public, it should work.
        target = TELEGRAM_CHANNEL
        if target.lstrip('-').isdigit():
            target_id = int(target)
            # Heuristic to determine Peer type
            if target_id < 0 and str(target_id).startswith("-100"):
                # Likely a Channel/Supergroup (requires access hash, usually needs get_entity)
                # But if get_entity fails, we can try PeerChannel but it might fail without hash.
                target = target_id
            elif target_id < 0:
                # Likely a Basic Chat (negative ID, no -100 prefix)
                # Convert to positive ID for PeerChat
                target = PeerChat(abs(target_id))
            else:
                # Positive ID usually means User
                target = target_id
            
        # Direct ID usage is often more robust for bots
        await client.send_message(target, message)
        logging.info("Message sent to Telegram successfully.")
        await client.disconnect()
    except Exception as e:
        logging.error(f"Failed to send Telegram message: {e}")

def fetch_new_articles():
    """Fetches articles from BigQuery ingested in the last 24 hours."""
    # Try to authenticate
    try:
        client = bigquery.Client(project=GCP_PROJECT_ID)
    except Exception as e:
        logging.error("❌ Google Cloud Authentication Failed.")
        logging.error("To fix this, either:")
        logging.error("1. Run 'gcloud auth application-default login' in your terminal.")
        logging.error("2. Or place the Service Account JSON file in this directory and update the script.")
        logging.error(f"Details: {e}")
        return pd.DataFrame()
    
    # Calculate timestamp for 24 hours ago
    yesterday = datetime.now() - timedelta(days=1)
    yesterday_str = yesterday.isoformat()

    query = f"""
        SELECT title, url, published_date, source_country
        FROM `{GCP_PROJECT_ID}.{BQ_DATASET_TABLE}`
        WHERE ingested_at > '{yesterday_str}'
        ORDER BY ingested_at DESC
    """
    
    try:
        logging.info("Fetching articles from BigQuery...")
        df = client.query(query).to_dataframe()
        logging.info(f"Fetched {len(df)} articles.")
        return df
    except Exception as e:
        logging.error(f"BigQuery fetch failed: {e}")
        return pd.DataFrame()

def analyze_and_select_news(df):
    """Uses Gemini to select top 3 news items and write a digest."""
    if df.empty:
        return None

    # Prepare data for LLM
    articles_text = ""
    for index, row in df.iterrows():
        articles_text += f"ID: {index}\nTitle: {row['title']}\nURL: {row['url']}\nDate: {row['published_date']}\n\n"

    prompt = f"""
    You are a news editor for a daily digest about Climate Change and Climate Rights.
    Below is a list of news articles from the last 24 hours.

    Task:
    1. Select the 3 most important and impactful news items regarding developments around climate change and climate rights.
    2. For each item, provide the Title, URL, and a brief reflection (2-3 sentences) on why this is relevant/important.
    3. Format the output as a clean, engaging Telegram message. Use emojis where appropriate.
    
    Articles:
    {articles_text}
    
    Output Format:
    🌍 **Daily Climate Rights Digest** 🌍
    
    1. **[Title]**
    [Reflection on relevance]
    🔗 [URL]
    
    2. **[Title]**
    ...
    
    3. **[Title]**
    ...
    """

    try:
        logging.info("Sending articles to Gemini for analysis...")
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        logging.error(f"Gemini analysis failed: {e}")
        return None

async def main():
    parser = argparse.ArgumentParser(description="Daily Digest Service")
    parser.add_argument("--test", action="store_true", help="Send a test message to Telegram")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and analyze articles but print digest to console instead of sending")
    parser.add_argument("--get-id", action="store_true", help="Listen for new messages to find Channel ID")
    args = parser.parse_args()

    if args.get_id:
        logging.info("--- Listening for Channel ID ---")
        logging.info("Please post a message in your private channel now...")
        
        client = TelegramClient('bot_session', TELEGRAM_API_ID, TELEGRAM_API_HASH)
        await client.start(bot_token=TELEGRAM_BOT_TOKEN)

        @client.on(events.NewMessage)
        async def handler(event):
            chat = await event.get_chat()
            print(f"\n📢 New Message Detected!")
            print(f"Chat Title: {chat.title}")
            print(f"Chat ID: {chat.id}")
            print(f"-------------------------")
            # We don't disconnect automatically so the user can see multiple if needed, 
            # or we can exit after one. Let's keep running until Ctrl+C.

        client.add_event_handler(handler)
        
        logging.info("Bot is running. Press Ctrl+C to stop.")
        await client.run_until_disconnected()
        return

    if args.test:
        logging.info("Running in TEST mode.")
        await send_telegram_message("🧪 This is a test message from the Daily Digest Service.")
        return

    # 1. Fetch Articles
    df = fetch_new_articles()
    if df.empty:
        logging.info("No new articles found to process.")
        return

    # 2. Analyze with Gemini
    digest_message = analyze_and_select_news(df)
    if not digest_message:
        logging.info("No digest generated.")
        return

    # 3. Post to Telegram
    if args.dry_run:
        logging.info("--- DRY RUN: Digest Output ---")
        print(digest_message)
        logging.info("--- End of Digest ---")
    else:
        logging.info("Posting digest to Telegram...")
        await send_telegram_message(digest_message)

if __name__ == "__main__":
    asyncio.run(main())
