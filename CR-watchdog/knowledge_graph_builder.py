import pandas as pd
import spacy
from spacy.pipeline import EntityRuler
from pinecone import Pinecone, ServerlessSpec
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer
import google.generativeai as genai
import random 
import logging
import time
import uuid
import os
import json
import re
import typing_extensions as typing
from dotenv import load_dotenv
import hashlib

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

class ClimateKnowledgeBase:
    def __init__(self, pinecone_api_key, pinecone_index_name, neo4j_uri, neo4j_auth, 
                 google_api_key=None, embedding_model="minilm", use_llm_extraction=False, 
                 checkpoint_file="ingestion_checkpoint.txt"):
        """
        Initialize connections, models, and extraction strategy.
        """
        self.embedding_type = embedding_model
        self.use_llm_extraction = use_llm_extraction
        self.checkpoint_file = checkpoint_file
        self.processed_ids = self._load_checkpoint()
        
        # 1. Initialize NLP (Always needed for fallback/cleaning)
        self.nlp = spacy.load("en_core_web_sm")
        self._setup_custom_ontology()

        # 2. Configure Google AI (if needed for Embeddings OR Extraction)
        if self.embedding_type == "google" or self.use_llm_extraction:
            if not google_api_key:
                raise ValueError("Google API Key required for Google Embeddings OR LLM Extraction.")
            genai.configure(api_key=google_api_key)

        # 3. Setup Embedding Models
        if self.embedding_type == "google":
            self.embedding_dim = 768
            logger.info("Using Google 'text-embedding-004' (768 dimensions)")
        else:
            self.embedder = SentenceTransformer('all-MiniLM-L6-v2')
            self.embedding_dim = 384
            logger.info("Using Local 'all-MiniLM-L6-v2' (384 dimensions)")

        # 4. Setup Extraction Model (if enabled)
        if self.use_llm_extraction:
            self.extraction_model = genai.GenerativeModel('gemini-2.5-flash')
            logger.info("✨ LLM Extraction Enabled (Gemini 2.5 Flash)")

        # 5. Initialize Pinecone
        self.pc = Pinecone(api_key=pinecone_api_key)
        self.index_name = pinecone_index_name
        self._init_pinecone_index()
        self.index = self.pc.Index(self.index_name)

        # 6. Initialize Neo4j
        self.driver = GraphDatabase.driver(neo4j_uri, auth=neo4j_auth)
        self.verify_neo4j_connection()


    # --- CHECKPOINT METHODS ---
    def _load_checkpoint(self):
        """Reads the log file to find IDs that are already done."""
        if not os.path.exists(self.checkpoint_file): return set()
        with open(self.checkpoint_file, "r") as f:
            ids = {line.strip() for line in f.readlines()}
        logger.info(f"🔄 Resuming: Found {len(ids)} already processed records.")
        return ids

    def _save_checkpoint(self, item_id):
        """Appends a single ID to the log file."""
        with open(self.checkpoint_file, "a") as f:
            f.write(f"{item_id}\n")
        self.processed_ids.add(item_id)


    def _init_pinecone_index(self):
        """
        Creates Pinecone index if it doesn't exist, ensuring correct dimensions.
        """
        existing_indexes = [i.name for i in self.pc.list_indexes()]
        
        if self.index_name not in existing_indexes:
            logger.info(f"Creating Pinecone index '{self.index_name}' with dimension {self.embedding_dim}...")
            self.pc.create_index(
                name=self.index_name,
                dimension=self.embedding_dim, 
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1") # Adjust region as needed
            )
        else:
            # Optional: Check if existing index matches dimension
            idx_desc = self.pc.describe_index(self.index_name)
            if int(idx_desc.dimension) != self.embedding_dim:
                logger.warning(f"⚠️ WARNING: Index '{self.index_name}' exists with dimension {idx_desc.dimension}, "
                               f"but current model uses {self.embedding_dim}. This will cause errors.")
                logger.warning("SOLUTION: Delete the index in Pinecone console or change the index name below.")

    def verify_neo4j_connection(self):
        try:
            self.driver.verify_connectivity()
            logger.info("Connected to Neo4j successfully.")
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            raise

    def _setup_custom_ontology(self):
        """
        Injects domain-specific knowledge into spaCy.
        """
        if "entity_ruler" not in self.nlp.pipe_names:
            ruler = self.nlp.add_pipe("entity_ruler", before="ner")
        else:
            ruler = self.nlp.get_pipe("entity_ruler")

        # DEFINE YOUR ONTOLOGY PATTERNS HERE
        patterns = [
            # --- POLLUTANTS ---
            {"label": "POLLUTANT", "pattern": [{"LOWER": "carbon"}, {"LOWER": "dioxide"}]},
            {"label": "POLLUTANT", "pattern": [{"LOWER": "co2"}]},
            {"label": "POLLUTANT", "pattern": [{"LOWER": "methane"}]},
            {"label": "POLLUTANT", "pattern": [{"LOWER": "coal"}]},
            {"label": "POLLUTANT", "pattern": [{"LOWER": "oil"}]},
            {"label": "POLLUTANT", "pattern": [{"LOWER": "plastic"}]},
            {"label": "POLLUTANT", "pattern": [{"LOWER": "fossil"}, {"LOWER": "fuels"}]},
            
            # --- HARMS ---
            {"label": "HARM", "pattern": [{"LOWER": "flooding"}]},
            {"label": "HARM", "pattern": [{"LOWER": "drought"}]},
            {"label": "HARM", "pattern": [{"LOWER": "displacement"}]},
            {"label": "HARM", "pattern": [{"LOWER": "asthma"}]},
            {"label": "HARM", "pattern": [{"LOWER": "cancer"}]},
            {"label": "HARM", "pattern": [{"LOWER": "erosion"}]},
            {"label": "HARM", "pattern": [{"LOWER": "deforestation"}]},
            
            # --- INFRASTRUCTURE / PROJECTS (New) ---
            {"label": "PROJECT", "pattern": [{"LOWER": "pipeline"}]},
            {"label": "PROJECT", "pattern": [{"LOWER": "mine"}]},
            {"label": "PROJECT", "pattern": [{"LOWER": "power"}, {"LOWER": "plant"}]},
            {"label": "PROJECT", "pattern": [{"LOWER": "dam"}]},
            {"label": "PROJECT", "pattern": [{"LOWER": "refinery"}]},

            # --- TREATIES (New) ---
            {"label": "TREATY", "pattern": [{"LOWER": "paris"}, {"LOWER": "agreement"}]},
            {"label": "TREATY", "pattern": [{"LOWER": "kyoto"}, {"LOWER": "protocol"}]},

            # --- LEGAL CONCEPTS ---
            {"label": "LEGAL_PRINCIPLE", "pattern": [{"LOWER": "precautionary"}, {"LOWER": "principle"}]},
            {"label": "LEGAL_PRINCIPLE", "pattern": [{"LOWER": "human"}, {"LOWER": "rights"}]},
            {"label": "LEGAL_PRINCIPLE", "pattern": [{"LOWER": "intergenerational"}, {"LOWER": "equity"}]},
        ]
        
        # Clear existing patterns to avoid duplicates if run multiple times
        ruler.clear()
        ruler.add_patterns(patterns)
        logger.info("Custom Ontology (Pollutants, Harms, Projects) loaded into NLP pipeline.")

    def close(self):
        self.driver.close()

    def _api_call_with_retry(self, func, *args, **kwargs):
        max_retries = 5
        base_delay = 2
        
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_str = str(e)
                # Check for server/rate errors (500, 503, 429)
                if "500" in error_str or "503" in error_str or "429" in error_str or "internal error" in error_str.lower():
                    sleep_time = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"⚠️ API Error ({e}). Retrying in {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
                else:
                    # If it's a 400 (Bad Request), DON'T retry. It will never succeed.
                    logger.error(f"❌ Deterministic Error (Not Retrying): {e}")
                    return None 
        
        logger.error(f"❌ API Failed after {max_retries} attempts.")
        return None

    def get_embedding(self, text):
        # 1. VALIDATION: Check for empty input
        if not text or not isinstance(text, str) or not text.strip():
            logger.warning("⚠️ Skipped embedding: Input is empty.")
            return []
        
        # Policies often have <p> tags that inflate token count without adding meaning
        clean_text = re.sub(r'<[^>]+>', '', text) 

        # Collapse whitespace
        clean_text = " ".join(clean_text.split())

        if self.embedding_type == "google":
            # 2. TRUNCATION: text-embedding-004 limit is ~2048 tokens (~8000 chars)
            # Sending more causes 500s or 400s.
            if len(text) > 7000:
                text = text[:7000] 

            def _call_google():
                result = genai.embed_content(
                    model="models/text-embedding-004",
                    content=text,
                    task_type="retrieval_document"
                )
                return result['embedding']

            return self._api_call_with_retry(_call_google)
        else:
            # Local embeddings handle truncation internally usually, but safe to truncate
            return self.embedder.encode(text[:8000]).tolist()

    def extract_entities_spacy(self, text):
        doc = self.nlp(text)
        entities = []
        for ent in doc.ents:
            label = ent.label_
            # Mapping
            if label == "ORG": label = "Company"
            elif label == "GPE": label = "Jurisdiction"
            elif label == "LOC": label = "Location"
            elif label == "PERSON": label = "Person"
            elif label == "NORP": label = "Group"
            elif label == "MONEY": label = "Financial"
            elif label == "LAW": label = "Law"
            elif label in ["POLLUTANT", "HARM", "LEGAL_PRINCIPLE", "PROJECT", "TREATY"]: pass 
            else: continue
            entities.append({"text": ent.text, "label": label})
        return entities

    def extract_entities_llm(self, text):
        # 1. VALIDATION
        if not text or not isinstance(text, str) or not text.strip():
            return []

        # Gemini 1.5 Flash has a 1M token window, so length is rarely the issue for 500s here.
        # But we still handle the call robustly.
        
        prompt = f"""
        Analyze the following legal text and extract entities matching these specific categories:
        - Company (Corporations, Banks)
        - Jurisdiction (Countries, States)
        - Location (Natural features like rivers, forests)
        - Person (Specific individuals)
        - Group (Indigenous groups, NGOs)
        - Financial (Monetary values, damages)
        - Law (Specific Acts, Bills)
        - Pollutant (Greenhouse gases, chemicals)
        - Harm (Environmental or health impacts like flooding, cancer)
        - Project (Infrastructure like pipelines, mines, dams)
        - Treaty (International agreements)
        - Legal_Principle (e.g., Precautionary Principle)

        Text: "{text}"

        Return ONLY a JSON list of objects with 'text' and 'label'. 
        Example: [{{"text": "Shell", "label": "Company"}}, {{"text": "methane", "label": "Pollutant"}}]
        """
        
        def _call_llm():
            response = self.extraction_model.generate_content(
                prompt, 
                generation_config={"response_mime_type": "application/json"}
            )
            return json.loads(response.text)

        result = self._api_call_with_retry(_call_llm)
        
        if result is None:
            return self.extract_entities_spacy(text)
        
        return result
        
    
    def ingest_dataset(self, df):
        total_records = len(df)
        skipped_count = 0
        logger.info(f"Starting ingestion of {total_records} records...")
        
        with self.driver.session() as session:
            for index, row in df.iterrows():
                case_id = str(row.get("ID", uuid.uuid4()))
                
                if case_id in self.processed_ids:
                    skipped_count += 1
                    continue

                case_name = row.get("Case Name", "Unknown Case")
                description = row.get("Description", "")
                principal_laws = str(row.get("Principal Laws", "")).split('|')
                
                if not description or pd.isna(description):
                    continue

                # 1. Embedding
                embedding = self.get_embedding(description)
                if not embedding: continue

                metadata = {
                    "type": "Case",
                    "case_name": case_name,
                    "jurisdiction": row.get("Jurisdiction", "Unknown"),
                    "year": str(row.get("Filing Year", "")),
                    "text": description[:1000]
                }
                
                try:
                    self.index.upsert(vectors=[(case_id, embedding, metadata)])
                except Exception as e:
                    logger.error(f"Pinecone Error: {e}")
                    continue 

                # 2. Knowledge Graph
                try:
                    tx = session.begin_transaction()
                    tx.run("""
                        MERGE (c:CourtCase {id: $id})
                        SET c.name = $name, c.description = $desc, c.year = $year
                    """, id=case_id, name=case_name, desc=description, year=str(row.get("Filing Year", "")))

                    for law in principal_laws:
                        if law.strip():
                            tx.run("""
                                MATCH (c:CourtCase {id: $id})
                                MERGE (l:Law {name: $law_name})
                                MERGE (c)-[:CITES]->(l)
                            """, id=case_id, law_name=law.strip())

                    # --- SWITCH: LLM vs SPACY ---
                    if self.use_llm_extraction:
                        # Add a small sleep to avoid hitting rate limits on Free Tier
                        time.sleep(1.0) 
                        extracted_ents = self.extract_entities_llm(description)
                    else:
                        extracted_ents = self.extract_entities_spacy(description)
                    # ----------------------------

                    for ent in extracted_ents:
                        # Sanitize label (ensure it's one of our allowed types to avoid injection)
                        label = ent.get('label', '').replace(" ", "_")
                        name = ent.get('text', '')
                        
                        if label and name:
                            tx.run(f"""
                                MATCH (c:CourtCase {{id: $id}})
                                MERGE (e:{label} {{name: $name}})
                                MERGE (c)-[:MENTIONS]->(e)
                            """, id=case_id, name=name)
                    
                    tx.commit()
                    self._save_checkpoint(case_id)

                except Exception as e:
                    logger.error(f"Neo4j Error on ID {case_id}: {e}")
                    continue 
                    
                if index % 10 == 0:
                    logger.info(f"Processed {index}/{total_records} records...")

        logger.info(f"Ingestion Complete. {skipped_count} skipped.")
        

    def ingest_policy_dataset(self, df):
        """
        Ingests the Climate Policy Radar (CPR) dataset.
        Maps 'The Rules' (Policies) to the Graph.
        """

        # --- SAFETY CHECK ---
        required_columns = ["Document ID", "Document Title", "Family Summary"]
        if not all(col in df.columns for col in required_columns):
            logger.error(f"❌ WRONG DATASET! Expected {required_columns}. Aborting.")
            return
        
        logger.info(f"📜 Starting POLICY ingestion of {len(df)} records...")
        
        with self.driver.session() as session:
            for index, row in df.iterrows():
                # --- 1. ID SANITIZATION (THE FIX) ---
                raw_id = str(row.get("Document ID", uuid.uuid4()))

                # If ID is too long for Pinecone, Hash it (SHA256 is always 64 chars)
                if len(raw_id) > 400: 
                    # We use 400 to leave room for "policy_" prefix
                    hashed_id = hashlib.sha256(raw_id.encode()).hexdigest()
                    policy_id = hashed_id
                    logger.warning(f"⚠️ ID too long ({len(raw_id)} chars). Hashed to: {policy_id}")
                else:
                    policy_id = raw_id
                
                # Checkpoint Check
                if policy_id in self.processed_ids:
                    continue

                title = row.get("Document Title", "Unknown Policy")
                summary = row.get("Family Summary", "")
                # Handle nan/empty summaries
                if pd.isna(summary): summary = title
                
                sectors = str(row.get("Sector", "")).split(";") 
                instruments = str(row.get("Instrument", "")).split(";")
                keywords = str(row.get("Keyword", "")).split(";")
                geography = row.get("Geographies", "Global") # e.g., "European Union"
                date_passed = str(row.get("First event in timeline", ""))

                # 1. Vector Embedding (The "Meaning" of the Law)
                # We use a different namespace or metadata to distinguish Law from Case
                embedding = self.get_embedding(summary)
                if embedding:
                    metadata = {
                        "type": "Policy",
                        "title": title,
                        "original_id": raw_id[:1000],
                        "jurisdiction": geography,
                        "year": date_passed[:4] if len(date_passed) >= 4 else "Unknown",
                        "keywords": ", ".join([k.strip() for k in keywords if k.strip()]),
                        "text": summary[:1000]
                    }
                    try:
                        self.index.upsert(vectors=[(f"policy_{policy_id}", embedding, metadata)])
                    except Exception as e:
                        logger.error(f"Pinecone Error on Policy {policy_id}: {e}")
                        continue

                # 2. Knowledge Graph (The "Structure" of the Law)
                try:
                    tx = session.begin_transaction()
                    
                    # A. Create Policy Node
                    tx.run("""
                        MERGE (p:Policy {id: $id})
                        SET p.title = $title, p.summary = $summary, p.date = $date
                    """, id=policy_id, title=title, summary=summary, date=date_passed)

                    # B. Link to Jurisdiction (The Bridge to Litigation)
                    # Note: We match the existing Jurisdiction node created by the Litigation ingestion
                    tx.run("""
                        MATCH (p:Policy {id: $id})
                        MERGE (j:Jurisdiction {name: $geo})
                        MERGE (p)-[:APPLIES_TO]->(j)
                    """, id=policy_id, geo=geography)

                    # C. Link to Sectors (The "Topic" Bridge)
                    for sec in sectors:
                        if sec.strip():
                            tx.run("""
                                MATCH (p:Policy {id: $id})
                                MERGE (s:Sector {name: $sec_name})
                                MERGE (p)-[:REGULATES]->(s)
                            """, id=policy_id, sec_name=sec.strip())

                    # D. Link to Instruments (The "Accountability" Tool)
                    for instr in instruments:
                        if instr.strip():
                            tx.run("""
                                MATCH (p:Policy {id: $id})
                                MERGE (i:Instrument {name: $instr_name})
                                MERGE (p)-[:USES]->(i)
                            """, id=policy_id, instr_name=instr.strip())
                    
                    # E. Link to Keywords (NEW)
                    for keyw in keywords:
                        if keyw.strip():
                            tx.run("""
                                MATCH (p:Policy {id: $id})
                                MERGE (k:Keyword {name: $key_name})
                                MERGE (p)-[:TAGGED_WITH]->(k)
                            """, id=policy_id, key_name=keyw.strip())

                    # F. LLM/Spacy Extraction on the Summary (Find Pollutants/Harms in the Law)
                    # This allows us to see if a law mentions "Methane"
                    if self.use_llm_extraction:
                        # Use same extraction logic as Cases
                        time.sleep(0.5)
                        extracted_ents = self.extract_entities_llm(summary)
                    else:
                        extracted_ents = self.extract_entities_spacy(summary)

                    for ent in extracted_ents:
                        label = ent.get('label', '').replace(" ", "_")
                        name = ent.get('text', '')
                        if label in ["POLLUTANT", "HARM", "PROJECT"] and name:
                            tx.run(f"""
                                MATCH (p:Policy {{id: $id}})
                                MERGE (e:{label} {{name: $name}})
                                MERGE (p)-[:ADDRESSES]->(e)
                            """, id=policy_id, name=name)

                    tx.commit()
                    self._save_checkpoint(policy_id)
                
                except Exception as e:
                    logger.error(f"Neo4j Error on Policy {policy_id}: {e}")
                    continue
                
                if index % 10 == 0:
                    logger.info(f"Processed {index} policies...")

        logger.info("Policy Ingestion Complete.")

# ==========================================
# EXAMPLE USAGE
# ==========================================
if __name__ == "__main__":
    # Configuration - REPLACE WITH YOUR KEYS
    PINECONE_KEY = os.getenv("PINECONE_API_KEY")
    NEO4J_URI = "neo4j+s://0dc47c9f.databases.neo4j.io"
    NEO4J_AUTH = ("neo4j", "ZG-TEicS5P4dROrWdaGrS7avHTymG1OLlihxq3J3hKQ")

    # Set this to True to use Gemini for "Smart" extraction (Slower but better)
    USE_LLM_EXTRACTION = False  

    # Set to True for High Precision (768 dims), False for Speed (384 dims)
    USE_GOOGLE_EMBEDDINGS = True 
    
    # Important: If you change models, change the index name too!
    # Pinecone cannot mix 384 and 768 dimension vectors in one index.
    PINECONE_INDEX = "climate-rights-agent-nollm" if USE_GOOGLE_EMBEDDINGS else "climate-agent-local"

    # --- 3. LOAD DATA ---
    # For testing, we create a dummy dataframe. In production, use pd.read_csv()
    data = {
        "ID": ["101", "102"],
        "Case Name": ["FutureGen v. EPA", "Residents v. OilCorp"],
        "Description": [
            "NGO sued the EPA regarding the Clean Air Act, arguing that carbon dioxide is a pollutant that endangers public health.",
            "Residents of the Niger Delta sued OilCorp for massive oil spills causing displacement and asthma in local communities."
        ],
        "Principal Laws": ["Clean Air Act", "Petroleum Industry Act"],
        "Filing Year": [2011, 2015],
        "Jurisdiction": ["USA", "Nigeria"]
    }
    file_path_cases = "./Data/CASES_COMBINED_status.csv"
    file_path_policy = "./Data/Document_Data_Download-2025-11-10.csv"

    llm_extrcation = False

    try:
        df_data = pd.read_csv(file_path_policy)
        print(f"Loaded {len(df_data)} policy records.")
    except FileNotFoundError:
        print("❌ Error: csv file not found.")
        exit()

    # --- 4. RUN BUILDER ---
    try:
        model_choice = "google" if USE_GOOGLE_EMBEDDINGS else "minilm"
        
        kb_builder = ClimateKnowledgeBase(
            pinecone_api_key=PINECONE_KEY, 
            pinecone_index_name=PINECONE_INDEX, 
            neo4j_uri=NEO4J_URI, 
            neo4j_auth=NEO4J_AUTH,
            google_api_key=os.getenv("GOOGLE_API_KEY"),
            embedding_model=model_choice, 
            use_llm_extraction=llm_extrcation
        )
        
        # kb_builder.ingest_dataset(df_data) # Step 1 add dataset to vector DB and KG
        kb_builder.ingest_policy_dataset(df_data) # Use this to add data to the vector database and KG iso of using the ingest_data_policy.py directly
        kb_builder.close()
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("Tip: Check your API keys and ensure you are not mixing dimensions in Pinecone.")