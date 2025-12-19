### This file adds additional data to the PINCONE_VECTOR_STORE
import pandas as pd
# Import your existing class from the builder file
from knowledge_graph_builder import ClimateKnowledgeBase
import os
from dotenv import load_dotenv


## Init
load_dotenv()

PINECONE_KEY = os.getenv("PINECONE_API_KEY")
NEO4J_URI = "neo4j+s://0dc47c9f.databases.neo4j.io"
NEO4J_AUTH = ("neo4j", os.getenv("NEO_API_KEY"))

## Config
USE_GOOGLE_EMBEDDINGS = True 
PINECONE_INDEX = "climate-rights-agent-nollm" if USE_GOOGLE_EMBEDDINGS else "climate-agent-local"
GOOGLE_KEY = os.getenv("GOOGLE_API_KEY")

if __name__ == "__main__":
    # 1. Load the Snippet Data
    # Ensure 'snippet_data.csv' is in the same folder
    try:
        df_policy = pd.read_csv("Data\Document_Data_Download-2025-11-10.csv")
        print(f"Loaded {len(df_policy)} policy records.")
    except FileNotFoundError:
        print("❌ Error: snippet_data.csv not found.")
        exit()

    # 2. Initialize Builder
    model_choice = "google" if USE_GOOGLE_EMBEDDINGS else "minilm"
    kb = ClimateKnowledgeBase(
        pinecone_api_key=PINECONE_KEY, 
        pinecone_index_name=PINECONE_INDEX, 
        neo4j_uri=NEO4J_URI, 
        neo4j_auth=NEO4J_AUTH,
        google_api_key=GOOGLE_KEY,
        embedding_model=model_choice,
        use_llm_extraction=True # Highly recommended for Policies to find "Methane", "Transport", etc.
    )

    # 3. Run Policy Ingestion
    kb.ingest_policy_dataset(df_policy)
    kb.close()