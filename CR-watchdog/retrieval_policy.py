import os
import logging
from typing import List, Dict, Any
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.chat_models import ChatOllama
from langchain_community.embeddings import OllamaEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from sentence_transformers import SentenceTransformer
from pinecone import Pinecone
from neo4j import GraphDatabase
import google.generativeai as genai
import json
import os
from dotenv import load_dotenv


load_dotenv()

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class HybridRetrievalEngine:
    def __init__(
        self, 
        pinecone_api_key: str,
        pinecone_index_name: str,
        neo4j_uri: str,
        neo4j_auth: tuple,
        google_api_key: str = None,
        use_ollama: bool = False,
        ollama_model: str = "llama3",
        embedding_model_type: str = "minilm" # 'google' or 'minilm' (MUST match what you used for ingestion!)
    ):
        """
        Args:
            embedding_model_type: MUST match the model used in knowledge_graph_builder.py 
                                  ('minilm' = 384 dims, 'google' = 768 dims)
        """
        self.use_ollama = use_ollama
        self.embedding_type = embedding_model_type
        
        # --- 1. SETUP LLM (The Reasoning Brain) ---
        if self.use_ollama:
            logger.info(f"🤖 Using Ollama ({ollama_model}) for reasoning...")
            self.llm = ChatOllama(model=ollama_model, temperature=0)
        else:
            if not google_api_key:
                raise ValueError("Google API Key required for Gemini.")
            logger.info("✨ Using Google Gemini 2.5 Flash for reasoning...")
            # Note: 'gemini-2.0-flash-exp' is the preview name, falling back to 1.5-flash if 2.0 not avail in your region
            self.llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash", 
                google_api_key=google_api_key,
                temperature=0
            )

        # --- 2. SETUP EMBEDDINGS (For Vector Search) ---
        # CRITICAL: This must match the dimension of your Pinecone index (384 or 768)
        if self.embedding_type == "google":
            if not google_api_key: raise ValueError("Google API Key required for embeddings.")
            self.embedder = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004", google_api_key=google_api_key)
            self.embedding_dim = 768
        else:
            # We use raw SentenceTransformer here to ensure exact match with builder script
            self.local_embedder = SentenceTransformer('all-MiniLM-L6-v2')
            self.embedding_dim = 384

        # --- 3. CONNECT TO DATABASES ---
        # Pinecone
        self.pc = Pinecone(api_key=pinecone_api_key)
        self.index = self.pc.Index(pinecone_index_name)
        
        # Neo4j
        self.driver = GraphDatabase.driver(neo4j_uri, auth=neo4j_auth)
        self.driver.verify_connectivity()
        logger.info("✅ Connected to Pinecone and Neo4j.")

    def _get_query_embedding(self, text: str) -> List[float]:
        """Helper to get embedding based on selected model."""
        if self.embedding_type == "google":
            return self.embedder.embed_query(text)
        else:
            return self.local_embedder.encode(text).tolist()

    # =======================================================
    # 🧠 LEG 1: VECTOR SEARCH (Pinecone)
    # =======================================================
    def query_vector_store(self, query: str, top_k: int = 5) -> str:
        """
        Searches Pinecone for semantically similar case descriptions.
        Returns a single string of context.
        """
        logger.info(f"🔍 Vector Search for: '{query}'")
        vector = self._get_query_embedding(query)
        
        results = self.index.query(
            vector=vector,
            top_k=top_k,
            include_metadata=True
        )
        
        context_pieces = []
        for match in results['matches']:
            meta = match['metadata']
            score = match['score']
            doc_type = meta.get('type', 'Case') # Default to 'Case' if missing
            
            if doc_type == 'Policy':
                # Format for Policies
                piece = f"[POLICY: {meta.get('title', 'Unknown')} ({meta.get('year', 'N/A')})] (Jurisdiction: {meta.get('jurisdiction', 'Global')}) (Score: {score:.2f})\nSUMMARY: {meta.get('text', '')}\n"
            else:
                # Format for Litigation Cases
                piece = f"[CASE: {meta.get('case_name', 'Unknown')} ({meta.get('year', 'N/A')})] (Jurisdiction: {meta.get('jurisdiction', 'Unknown')}) (Score: {score:.2f})\nDESC: {meta.get('text', '')}\n"
            
            context_pieces.append(piece)
            
        return "\n".join(context_pieces)

    # =======================================================
    # 🕸️ LEG 2: GRAPH SEARCH (Neo4j)
    # =======================================================
    def extract_entities_for_graph(self, query: str) -> List[str]:
        """
        Uses the LLM to figure out which Entities (Companies, Pollutants, etc.) 
        are in the user's question so we can query the Graph.
        """
        prompt = ChatPromptTemplate.from_template("""
        Extract the key named entities from this user query that would likely exist in a climate litigation database.
        Focus on: Companies, Jurisdictions (Countries/Cities), Specific Laws, Pollutants, or Harms.
        
        Query: "{query}"
        
        Return ONLY a comma-separated list of names. If none, return "NONE".
        Example Output: Shell, Nigeria, Carbon Dioxide
        """)
        
        chain = prompt | self.llm | StrOutputParser()
        response = chain.invoke({"query": query})
        
        if "NONE" in response: return []
        return [x.strip() for x in response.split(",")]

    def query_graph_db(self, entities: List[str]) -> str:
        """
        Queries Neo4j for facts connected to the extracted entities.
        """
        if not entities:
            return "No specific entities identified for Graph Search."
            
        logger.info(f"🕸️ Graph Search for entities: {entities}")
        
        context_lines = []
        with self.driver.session() as session:
            for entity in entities:
                # 1. Find Cases
                cypher_cases = """
                MATCH (e {name: $name})<-[:MENTIONS]-(c:CourtCase)
                RETURN e.name as Entity, labels(e) as Type, c.name as Case, c.year as Year
                LIMIT 3
                """
                result_c = session.run(cypher_cases, name=entity)
                for r in result_c:
                    context_lines.append(f"- Entity '{r['Entity']}' is involved in CASE '{r['Case']}' ({r['Year']}).")

                # 2. Find Policies (The Rules) - NEW!
                # Finds policies that REGULATE a Sector or ADDRESS a Pollutant/Harm
                cypher_policies = """
                MATCH (e {name: $name})<-[r]-(p:Policy)
                RETURN e.name as Entity, type(r) as Relation, p.title as Policy, p.date as Date
                LIMIT 3
                """
                result_p = session.run(cypher_policies, name=entity)
                for r in result_p:
                    context_lines.append(f"- Entity '{r['Entity']}' is {r['Relation']} by POLICY '{r['Policy']}' ({r['Date']}).")

        return "\n".join(context_lines) if context_lines else "No direct graph connections found."

    # =======================================================
    # 🚀 HYBRID ORCHESTRATOR
    # =======================================================
    def ask(self, query: str) -> str:
        """
        The main entry point.
        1. Get Vector Context
        2. Get Graph Context
        3. Synthesize Answer via LLM
        """
        print(f"\n🤔 USER ASKS: {query}")
        
        # 1. Parallel Retrieval (Conceptually)
        vector_context = self.query_vector_store(query)
        
        # 2. Entity Extraction & Graph Query
        entities = self.extract_entities_for_graph(query)
        graph_context = self.query_graph_db(entities)
        
        # 3. Synthesis Prompt
        final_prompt = ChatPromptTemplate.from_template("""
        You are a Strategic Climate Accountability Analyst.
        Your goal is to identify gaps between "The Rules" (Policies) and "The Reality" (Litigation).
        
        --- VECTOR CONTEXT (Semantic Search) ---
        {vector_context}
        
        --- GRAPH CONTEXT (Factual Connections) ---
        {graph_context}
        
        --- USER QUESTION ---
        {query}
        
        INSTRUCTIONS:
        1. Synthesize findings from both Policies and Cases.
        2. Look for contradictions: Does a country have a strict policy (e.g. "Phase out coal") but recent cases about expanding it?
        3. Highlight specific actors (Companies/States) mentioned in both layers.
        4. Provide actionable insights for an investigator or activist.
        
        Answer:
        """)
        
        chain = final_prompt | self.llm | StrOutputParser()
        
        print("⚡ Generating Hybrid Response...")
        response = chain.invoke({
            "query": query,
            "vector_context": vector_context,
            "graph_context": graph_context
        })
        
        return response

# ==========================================
# EXECUTION BLOCK
# ==========================================
if __name__ == "__main__":
    # --- CONFIGURATION ---
    PINECONE_KEY = os.getenv("PINECONE_API_KEY")
    PINECONE_INDEX = "climate-rights-agent-nollm" # Or "climate-agent-google" depending on what you built!
    NEO4J_URI = "neo4j+s://0dc47c9f.databases.neo4j.io"
    NEO4J_AUTH = ("neo4j", "ZG-TEicS5P4dROrWdaGrS7avHTymG1OLlihxq3J3hKQ")
    GOOGLE_KEY = os.getenv("GOOGLE_API_KEY")
    
    # Select your Embedding Model (MUST MATCH THE BUILDER SCRIPT!)
    # "minilm" (384) or "google" (768)
    EMBEDDING_TYPE = "google" 

    # Select your LLM Brain
    USE_OLLAMA = False # Set True to use local Llama3
    
    try:
        engine = HybridRetrievalEngine(
            pinecone_api_key=PINECONE_KEY,
            pinecone_index_name=PINECONE_INDEX,
            neo4j_uri=NEO4J_URI,
            neo4j_auth=NEO4J_AUTH,
            google_api_key=GOOGLE_KEY,
            use_ollama=USE_OLLAMA,
            embedding_model_type=EMBEDDING_TYPE
        )
        
        # Test Query
        # query = "What legal actions have been taken regarding massive oil spills affecting local communities?"
        # query = "What is the best strategy to win a case against oil companies?"
        query = "What policies exist regarding coal phase out and are there legal cases challenging coal plants?" # for policy Update
        answer = engine.ask(query)
        
        print("\n================ RESPONSE ================")
        print(answer)
        print("==========================================")

    except Exception as e:
        print(f"Error: {e}")