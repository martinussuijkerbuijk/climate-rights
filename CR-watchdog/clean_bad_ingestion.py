import os
from pinecone import Pinecone
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
PINECONE_KEY = os.getenv("PINECONE_API_KEY")
NEO4J_URI = "neo4j+s://0dc47c9f.databases.neo4j.io"
NEO4J_AUTH = ("neo4j", "ZG-TEicS5P4dROrWdaGrS7avHTymG1OLlihxq3J3hKQ")

# IMPORTANT: Set this to the name of the index where the bad data went
PINECONE_INDEX_NAME = "climate-rights-agent-nollm" 

# Name of the file containing the IDs to delete (one per line)
BAD_IDS_FILE = "bad_ids.txt"

def load_bad_ids(filepath):
    """Reads IDs from a text file."""
    if not os.path.exists(filepath):
        print(f"❌ Error: File '{filepath}' not found. Please create it and paste the bad IDs there.")
        return []
    
    with open(filepath, "r") as f:
        # Read lines, strip whitespace/newlines, ignore empty lines
        ids = [line.strip() for line in f.readlines() if line.strip()]
    
    print(f"📄 Loaded {len(ids)} IDs from {filepath}")
    return ids

def clean_up():
    # 1. Load IDs
    bad_ids = load_bad_ids(BAD_IDS_FILE)
    if not bad_ids:
        print("No IDs to clean. Exiting.")
        return

    print(f"🚨 STARTING SURGICAL DELETION OF {len(bad_ids)} RECORDS 🚨")

    # 2. Delete from PINECONE
    print(f"\n--- 1. Cleaning Pinecone ({PINECONE_INDEX_NAME}) ---")
    try:
        pc = Pinecone(api_key=PINECONE_KEY)
        index = pc.Index(PINECONE_INDEX_NAME)
        
        # We delete both raw IDs and "policy_" prefixed IDs to be thorough
        prefixed_ids = [f"policy_{x}" for x in bad_ids]
        all_targets = bad_ids + prefixed_ids
        
        # Batching deletes (Pinecone has a limit per request)
        batch_size = 100
        for i in range(0, len(all_targets), batch_size):
            batch = all_targets[i:i + batch_size]
            index.delete(ids=batch)
            print(f"   - Sent delete batch {(i // batch_size) + 1}")
            
        print(f"✅ Cleanup commands sent for {len(all_targets)} potential vectors.")
    except Exception as e:
        print(f"❌ Pinecone Error: {e}")

    # 3. Delete from NEO4J
    print(f"\n--- 2. Cleaning Neo4j ---")
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
        with driver.session() as session:
            for item_id in bad_ids:
                # This query deletes ANY node with this ID, whether it's a Policy or CourtCase
                # It also deletes any relationships connected to it (DETACH)
                query = "MATCH (n {id: $id}) DETACH DELETE n"
                session.run(query, id=item_id)
                print(f"   - Deleted Node ID: {item_id}")
        driver.close()
        print("✅ Neo4j cleanup complete.")
    except Exception as e:
        print(f"❌ Neo4j Error: {e}")

    # 4. Clean the CHECKPOINT FILE
    print(f"\n--- 3. Cleaning Checkpoint File ---")
    checkpoint_file = "ingestion_checkpoint.txt"
    if os.path.exists(checkpoint_file):
        with open(checkpoint_file, "r") as f:
            lines = f.readlines()
        
        # Filter out the bad IDs (stripped for accurate matching)
        bad_ids_set = set(bad_ids)
        clean_lines = [line for line in lines if line.strip() not in bad_ids_set]
        
        with open(checkpoint_file, "w") as f:
            f.writelines(clean_lines)
        
        removed_count = len(lines) - len(clean_lines)
        print(f"✅ Removed {removed_count} lines from {checkpoint_file}.")
    else:
        print("⚠️ Checkpoint file not found.")

if __name__ == "__main__":
    print(f"This script will read IDs from '{BAD_IDS_FILE}' and delete them from Pinecone, Neo4j, and the checkpoint.")
    confirm = input("Are you sure you want to proceed? (yes/no): ")
    if confirm.lower() == "yes":
        clean_up()
    else:
        print("Operation cancelled.")