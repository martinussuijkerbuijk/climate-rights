#!/usr/bin/env python3
"""
Final Climate Litigation GraphRAG System
Command-line interface with OpenAI and Gemini support.

Usage:
    python graphrag_cli.py --query "Your question here" --llm openai
    python graphrag_cli.py --query "Your question here" --llm gemini
    python graphrag_cli.py --query "Your question here" --no-llm
"""

import argparse
import json
import pandas as pd
import numpy as np
import pickle
import os
import sys
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
import networkx as nx
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import re
from dotenv import load_dotenv
from collections import Counter
import hashlib


load_dotenv() # loads the environment variables

class QueryType(Enum):
    """Different types of queries the system can handle."""
    ANALYTICAL = "analytical"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"

class LLMProvider:
    """Abstract base class for LLM providers."""
    
    def generate_response(self, prompt: str, max_tokens: int = 1000) -> str:
        raise NotImplementedError

class OpenAIProvider(LLMProvider):
    """OpenAI LLM provider."""
    
    def __init__(self, api_key: str = None, model: str = "gpt-4o-mini"):
        try:
            import openai
            self.client = openai.OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
            self.model = model
            
            # Test the connection
            self.client.models.list()
            print(f"✅ OpenAI connected successfully (model: {model})")
        except ImportError:
            raise ImportError("OpenAI library not installed. Run: pip install openai")
        except Exception as e:
            raise Exception(f"Failed to initialize OpenAI: {e}")
    
    def generate_response(self, prompt: str, max_tokens: int = 1000) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.5 # Lowered for more factual responses
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error generating OpenAI response: {str(e)}"

class GeminiProvider(LLMProvider):
    """Google Gemini LLM provider."""
    
    def __init__(self, api_key: str = None, model: str = "gemini-1.5-flash"):
        try:
            import google.generativeai as genai
            self.genai = genai
            
            api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if not api_key:
                raise ValueError("Gemini API key not found. Set GEMINI_API_KEY or GOOGLE_API_KEY environment variable.")
            
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(model)
            
            # Test the connection
            test_response = self.model.generate_content("Hello")
            print(f"✅ Gemini connected successfully (model: {model})")
        except ImportError:
            raise ImportError("Google AI library not installed. Run: pip install google-generativeai")
        except Exception as e:
            raise Exception(f"Failed to initialize Gemini: {e}")
    
    def generate_response(self, prompt: str, max_tokens: int = 1000) -> str:
        try:
            generation_config = self.genai.types.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=0.5, # Lowered for more factual responses
            )
            
            response = self.model.generate_content(
                prompt,
                generation_config=generation_config
            )
            return response.text
        except Exception as e:
            return f"Error generating Gemini response: {str(e)}"

class QueryRouter:
    """Intelligent query router for determining query handling strategy."""
    
    def __init__(self):
        # --- CHANGE 1: Expanded regex patterns for better coverage ---
        self.analytical_patterns = [
            r'\b(how many|count|number of)\b',
            r'\b(most|least|top|bottom|highest|lowest)\b',
            r'\b(rank|ranking|compare|comparison)\b',
            r'\b(total|sum|average|mean|median)\b',
            r'\b(which .+ have the most|what .+ has the most)\b',
            r'\b(list all|show all)\b',
            r'\b(statistics|stats|distribution|breakdown)\b'
        ]
        
        self.semantic_patterns = [
            r'\b(what is|what are|explain|describe|tell me about|summarize)\b',
            r'\b(why|how|when|where)\b',
            r'\b(relationship|connection|related to|link between)\b',
            r'\b(impact|effect|influence|consequence)\b',
            r'\b(examples of|instances of|types of)\b',
            r'\b(strategies|approaches|methods)\b'
        ]
    
    def classify_query(self, query: str) -> Tuple[QueryType, float]:
        """Classify a query and return confidence score."""
        query_lower = query.lower()
        
        analytical_matches = sum(1 for pattern in self.analytical_patterns 
                             if re.search(pattern, query_lower))
        semantic_matches = sum(1 for pattern in self.semantic_patterns 
                           if re.search(pattern, query_lower))
        
        # Calculate confidence as the ratio of matched patterns to total patterns
        analytical_confidence = analytical_matches / len(self.analytical_patterns) if self.analytical_patterns else 0
        semantic_confidence = semantic_matches / len(self.semantic_patterns) if self.semantic_patterns else 0

        # Determine query type based on which confidence score is higher
        if analytical_confidence > 0 and semantic_confidence > 0:
            # For hybrid, confidence can be the average of the two
            confidence = (analytical_confidence + semantic_confidence) / 2
            return QueryType.HYBRID, confidence
        elif analytical_confidence > semantic_confidence:
            return QueryType.ANALYTICAL, analytical_confidence
        elif semantic_confidence > analytical_confidence:
            return QueryType.SEMANTIC, semantic_confidence
        else:
            # If scores are equal (including both being 0), it's unknown
            return QueryType.UNKNOWN, 0.0

class ClimateGraphRAG:
    """Production Climate Litigation GraphRAG System."""
    
    def __init__(self, graph_json_path: str, original_csv_path: str = None,
                 embedding_model: str = "all-MiniLM-L6-v2", cache_dir: str = "_cache"):
        """Initialize the GraphRAG system."""
        
        print("🚀 Initializing Climate Litigation GraphRAG System...")
        
        # Validate input files
        if not os.path.exists(graph_json_path):
            raise FileNotFoundError(f"Graph JSON file not found: {graph_json_path}")
        
        self.graph_json_path = graph_json_path
        self.original_csv_path = original_csv_path
        self.cache_dir = cache_dir
        self.embedding_model_name = embedding_model
        
        # Initialize components
        self.query_router = QueryRouter()
        self.graph = self._load_graph(graph_json_path)
        self.df = self._load_original_data() if original_csv_path else None
        
        # Initialize embedding model and load/create embeddings
        print("📊 Loading sentence transformer model...")
        self.embedding_model = SentenceTransformer(embedding_model)
        self.node_embeddings = self._load_or_create_embeddings()
        
        # Pre-compute analytical summaries
        self.analytical_cache = self._create_analytical_cache()
        
        print("✅ GraphRAG system initialized successfully!\n")
    
    def _load_graph(self, json_path: str) -> nx.Graph:
        """Load the knowledge graph from JSON into NetworkX."""
        with open(json_path, 'r') as f:
            data = json.load(f)
        
        G = nx.Graph()
        
        for node in data['nodes']:
            G.add_node(node['id'], **node)
        
        for link in data['links']:
            G.add_edge(link['source'], link['target'], type=link['type'])
            
        print(f"📈 Graph loaded: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
        return G
    
    def _load_original_data(self) -> Optional[pd.DataFrame]:
        """Load original CSV data for analytical queries."""
        if not self.original_csv_path or not os.path.exists(self.original_csv_path):
            print("⚠️  Original CSV not found - analytical queries will be limited")
            return None
        
        try:
            df = pd.read_csv(self.original_csv_path)
            print(f"📋 Original data loaded: {len(df)} cases")
            return df
        except Exception as e:
            print(f"❌ Error loading CSV: {e}")
            return None
    
    def _get_embedding_cache_path(self) -> str:
        """Generate cache path for embeddings."""
        with open(self.graph_json_path, 'rb') as f:
            graph_hash = hashlib.md5(f.read()).hexdigest()[:8]
        
        model_hash = hashlib.md5(self.embedding_model_name.encode()).hexdigest()[:8]
        cache_filename = f"embeddings_{graph_hash}_{model_hash}.pkl"
        
        os.makedirs(self.cache_dir, exist_ok=True)
        return os.path.join(self.cache_dir, cache_filename)
    
    def _load_or_create_embeddings(self) -> Dict[str, np.ndarray]:
        """Load embeddings from cache or create if not exist."""
        cache_path = self._get_embedding_cache_path()
        
        if os.path.exists(cache_path):
            print(f"📦 Loading embeddings from cache...")
            with open(cache_path, 'rb') as f:
                return pickle.load(f)
        else:
            print("🔄 Creating embeddings (this may take a moment)...")
            embeddings = self._create_embeddings()
            
            with open(cache_path, 'wb') as f:
                pickle.dump(embeddings, f)
            print(f"💾 Embeddings cached for future use")
            
            return embeddings
    
    def _create_embeddings(self) -> Dict[str, np.ndarray]:
        """Create embeddings for all nodes."""
        embeddings = {}
        
        for node_id, node_data in self.graph.nodes(data=True):
            text_parts = []
            
            if 'name' in node_data:
                text_parts.append(node_data['name'])
            if 'description' in node_data:
                text_parts.append(node_data['description'])
            if 'type' in node_data:
                text_parts.append(f"Type: {node_data['type']}")
                
            text_content = " ".join(text_parts)
            embedding = self.embedding_model.encode(text_content)
            embeddings[node_id] = embedding
            
        return embeddings
    
    def _create_analytical_cache(self) -> Dict[str, Any]:
        """Pre-compute common analytical queries."""
        cache = {}
        
        if self.df is None:
            return cache
        
        try:
            # Jurisdiction analysis
            if 'Jurisdictions' in self.df.columns:
                jurisdiction_counts = self.df['Jurisdictions'].dropna().str.split(r'[,;|]').explode().str.strip().value_counts()
                cache['jurisdiction_counts'] = jurisdiction_counts.to_dict()
                cache['top_jurisdictions'] = jurisdiction_counts.head(10).to_dict()
            
            # Topic analysis
            if 'Topic_Name' in self.df.columns:
                topic_counts = self.df['Topic_Name'].dropna().str.split(r'[,;|]').explode().str.strip().value_counts()
                cache['topic_counts'] = topic_counts.to_dict()
                cache['top_topics'] = topic_counts.head(10).to_dict()
            
            # Status analysis
            if 'Status' in self.df.columns:
                status_counts = self.df['Status'].value_counts()
                cache['status_distribution'] = status_counts.to_dict()
            
            # Year analysis
            if 'Filing Year' in self.df.columns:
                year_counts = self.df['Filing Year'].dropna().value_counts().sort_index()
                cache['cases_by_year'] = year_counts.to_dict()
                cache['total_cases'] = len(self.df)
            
            # Category analysis
            if 'Case Categories' in self.df.columns:
                category_counts = self.df['Case Categories'].dropna().str.split(r'[,;|]').explode().str.strip().value_counts()
                cache['category_counts'] = category_counts.to_dict()
            
            print(f"🔍 Pre-computed {len(cache)} analytical summaries")
            
        except Exception as e:
            print(f"⚠️  Error creating analytical cache: {e}")
        
        return cache
    
    def handle_analytical_query(self, query: str) -> Dict[str, Any]:
        """Handle analytical queries using pre-computed data."""
        query_lower = query.lower()
        results = {'query_type': 'analytical', 'data': {}, 'answer': ''}
        
        if 'jurisdiction' in query_lower and ('most' in query_lower or 'count' in query_lower):
            if 'jurisdiction_counts' in self.analytical_cache:
                results['data'] = self.analytical_cache['top_jurisdictions']
                top_jurisdiction = max(self.analytical_cache['jurisdiction_counts'].items(), key=lambda x: x[1])
                results['answer'] = f"The jurisdiction with the most climate cases is {top_jurisdiction[0]} with {top_jurisdiction[1]} cases."
                
                top_5 = list(self.analytical_cache['top_jurisdictions'].items())[:5]
                results['answer'] += f" Top 5: {', '.join([f'{j} ({c})' for j, c in top_5])}"
        
        elif 'topic' in query_lower and ('most' in query_lower or 'main' in query_lower):
            if 'topic_counts' in self.analytical_cache:
                results['data'] = self.analytical_cache['top_topics']
                top_topic = max(self.analytical_cache['topic_counts'].items(), key=lambda x: x[1])
                results['answer'] = f"The most common topic is '{top_topic[0]}' with {top_topic[1]} cases."
        
        elif 'status' in query_lower:
            if 'status_distribution' in self.analytical_cache:
                results['data'] = self.analytical_cache['status_distribution']
                total = sum(self.analytical_cache['status_distribution'].values())
                status_summary = ', '.join([f"{status}: {count} ({count/total*100:.1f}%)" 
                                          for status, count in self.analytical_cache['status_distribution'].items()])
                results['answer'] = f"Case status distribution: {status_summary}"
        
        elif 'year' in query_lower or 'trend' in query_lower:
            if 'cases_by_year' in self.analytical_cache:
                results['data'] = self.analytical_cache['cases_by_year']
                years_data = self.analytical_cache['cases_by_year']
                peak_year = max(years_data.items(), key=lambda x: x[1])
                results['answer'] = f"Peak year: {peak_year[0]} ({peak_year[1]} cases). Total: {sum(years_data.values())} cases"
        
        elif 'how many' in query_lower and 'total' in query_lower:
            if 'total_cases' in self.analytical_cache:
                results['data'] = {'total_cases': self.analytical_cache['total_cases']}
                results['answer'] = f"Total climate cases: {self.analytical_cache['total_cases']}"
        
        else:
            results['answer'] = "This seems to be an analytical query, but I couldn't find a specific pre-computed answer. Available analytics cover: jurisdictions, topics, case status, filing years, and total case counts."
        
        return results
    
    def semantic_search(self, query: str, top_k: int = 10) -> List[tuple]:
        """Find most semantically similar nodes."""
        query_embedding = self.embedding_model.encode(query)
        similarities = []
        
        for node_id, node_embedding in self.node_embeddings.items():
            similarity = cosine_similarity([query_embedding], [node_embedding])[0][0]
            similarities.append((node_id, similarity))
        
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:top_k]
    
    def graph_traversal_search(self, start_nodes: List[str], max_depth: int = 2) -> Dict[str, Any]:
        """Perform graph traversal from starting nodes."""
        subgraph_nodes = set(start_nodes)
        
        for _ in range(max_depth):
            # Create a copy of the set to iterate over while modifying the original
            current_nodes = list(subgraph_nodes)
            for node in current_nodes:
                if node in self.graph:
                    neighbors = list(self.graph.neighbors(node))
                    subgraph_nodes.update(neighbors)
        
        subgraph = self.graph.subgraph(subgraph_nodes)
        
        nodes_by_type = {}
        for node_id in subgraph_nodes:
            if node_id in self.graph:
                node_data = self.graph.nodes[node_id]
                node_type = node_data.get('type', 'Unknown')
                if node_type not in nodes_by_type:
                    nodes_by_type[node_type] = []
                nodes_by_type[node_type].append({
                    'id': node_id,
                    'name': node_data.get('name', node_id),
                    'data': node_data
                })
        
        return {
            'nodes_by_type': nodes_by_type,
            'subgraph': subgraph,
            'total_nodes': len(subgraph_nodes)
        }
    
    def handle_semantic_query(self, query: str, llm_provider: Optional[LLMProvider] = None) -> Dict[str, Any]:
        """Handle semantic queries using graph RAG."""
        semantic_results = self.semantic_search(query, top_k=15)
        semantic_nodes = [node_id for node_id, _ in semantic_results]
        graph_results = self.graph_traversal_search(semantic_nodes, max_depth=2)
        
        # --- CHANGE 3: More structured and detailed context generation ---
        context_parts = []
        context_parts.append("## Top 5 Most Relevant Entities from Knowledge Graph:")
        for node_id, score in semantic_results[:5]:
            if node_id in self.graph:
                node_data = self.graph.nodes[node_id]
                name = node_data.get('name', node_id)
                ntype = node_data.get('type', 'Unknown')
                desc = node_data.get('description', 'No description available.')
                context_parts.append(f"- Entity: '{name}' (Type: {ntype}, Relevance Score: {score:.2f})")
                context_parts.append(f"  - Description: {desc}")
        
        context_parts.append("\n## Expanded Context (Related Entities Found via Graph Traversal):")
        for node_type, nodes in graph_results['nodes_by_type'].items():
            if nodes:
                context_parts.append(f"\n### Related {node_type}s:")
                node_names = [node['name'] for node in nodes[:5]] # Get top 5 names
                context_parts.append("- " + ", ".join(node_names))

        context = "\n".join(context_parts)
        
        result = {
            'query_type': 'semantic',
            'context': context,
            'semantic_results': semantic_results,
            'graph_results': graph_results
        }
        
        if llm_provider:
            # --- CHANGE 4: Improved, more directive LLM prompt ---
            prompt = f"""You are an expert legal analyst. Your task is to synthesize the provided data from a climate litigation knowledge graph to answer the user's question. Identify key themes, relationships, and examples from the context. Structure your answer clearly.

**IMPORTANT:** Base your answer *exclusively* on the information provided in the context below. Do not use outside knowledge.

**Knowledge Graph Context:**
---
{context}
---

**User's Question:** {query}

**Synthesized Answer:**
"""
            result['generated_answer'] = llm_provider.generate_response(prompt)
        
        return result
    
    def query(self, question: str, llm_provider: Optional[LLMProvider] = None) -> Dict[str, Any]:
        """Main query interface with intelligent routing."""
        
        query_type, confidence = self.query_router.classify_query(question)
        
        # --- CHANGE 5: Fallback for UNKNOWN queries ---
        # If the router is unsure, default to a semantic search. This is much more helpful.
        if query_type == QueryType.UNKNOWN:
            print(f"🔍 Query classified as: UNKNOWN. Defaulting to SEMANTIC search.")
            query_type = QueryType.SEMANTIC
        else:
            print(f"🔍 Query classified as: {query_type.value} (confidence: {confidence:.2f})")

        if query_type == QueryType.ANALYTICAL:
            result = self.handle_analytical_query(question)
            result['classification'] = {'type': query_type.value, 'confidence': confidence}
            return result
            
        elif query_type == QueryType.SEMANTIC:
            result = self.handle_semantic_query(question, llm_provider)
            result['classification'] = {'type': query_type.value, 'confidence': confidence}
            return result
            
        elif query_type == QueryType.HYBRID:
            analytical_result = self.handle_analytical_query(question)
            semantic_result = self.handle_semantic_query(question, llm_provider)
            
            # Combine results for a comprehensive hybrid answer
            combined_answer = (analytical_result.get('answer', '') + 
                               "\n\n--- Further Context & Explanation ---\n" + 
                               semantic_result.get('generated_answer', semantic_result.get('context', '')))
            
            return {
                'query_type': 'hybrid',
                'classification': {'type': query_type.value, 'confidence': confidence},
                'analytical_component': analytical_result,
                'semantic_component': semantic_result,
                'answer': combined_answer.strip()
            }
            
        # This part should ideally not be reached due to the fallback
        return {
            'query_type': 'unknown',
            'classification': {'type': QueryType.UNKNOWN.value, 'confidence': 0.0},
            'answer': "I was unable to process this query."
        }


def create_llm_provider(provider_name: str) -> Optional[LLMProvider]:
    """Create LLM provider based on name."""
    if provider_name.lower() == 'openai':
        try:
            return OpenAIProvider()
        except Exception as e:
            print(f"❌ OpenAI setup failed: {e}")
            return None
    elif provider_name.lower() == 'gemini':
        try:
            return GeminiProvider()
        except Exception as e:
            print(f"❌ Gemini setup failed: {e}")
            return None
    else:
        print(f"❌ Unknown LLM provider: {provider_name}")
        return None

def print_response(result: Dict[str, Any], show_context: bool = False):
    """Pretty print the response."""
    print(f"\n{'='*60}")
    print(f"📋 Query Type: {result.get('classification', {}).get('type', 'unknown').upper()}")
    
    answer = result.get('answer') or result.get('generated_answer')
    
    if answer:
        print(f"📝 Answer:")
        print(answer)
    else:
        print("📝 No direct answer could be generated.")

    if show_context and 'context' in result:
        print(f"\n{'---'*20}\n📊 Retrieved Context (for debugging):\n{'---'*20}")
        print(result['context'])
    
    if 'data' in result and result['data']:
        print(f"\n📈 Supporting Data:")
        for key, value in result['data'].items():
            if isinstance(value, dict):
                print(f"  - {key}: {dict(list(value.items())[:5])}...")
            else:
                print(f"  - {key}: {value}")
    
    print(f"{'='*60}\n")

def main():
    """Command-line interface for the GraphRAG system."""
    
    parser = argparse.ArgumentParser(
        description="Climate Litigation GraphRAG System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python graphrag_cli.py --query "Which jurisdictions have the most climate cases?" --llm openai
  python graphrag_cli.py --query "Explain climate litigation strategies" --llm gemini
  python graphrag_cli.py --query "How many total cases are there?" --no-llm
  python graphrag_cli.py --interactive --llm openai
        """
    )
    
    parser.add_argument('--query', '-q', type=str, help='Query to ask the system')
    parser.add_argument('--llm', choices=['openai', 'gemini'], default='gemini', help='LLM provider to use')
    parser.add_argument('--no-llm', action='store_true', help='Use without LLM (faster, context only)')
    parser.add_argument('--interactive', '-i', action='store_true', help='Enter interactive mode')
    parser.add_argument('--graph-json', default='KG-climate-cases/data/knowledge_graph.json', 
                       help='Path to graph JSON file')
    parser.add_argument('--csv-data', default='_DATA/GLOBAL_cases_with_topics_named.csv',
                       help='Path to original CSV data')
    parser.add_argument('--show-context', action='store_true', help='Show retrieved context for debugging')
    parser.add_argument('--cache-dir', default='_cache', help='Directory for caching')
    
    args = parser.parse_args()
    
    # Validate arguments
    if not args.interactive and not args.query:
        parser.error("Either --query or --interactive must be specified")
    
    if args.llm and args.no_llm:
        parser.error("Cannot specify both --llm and --no-llm")
    
    # Initialize system
    try:
        graph_rag = ClimateGraphRAG(
            graph_json_path=args.graph_json,
            original_csv_path=args.csv_data if os.path.exists(args.csv_data) else None,
            cache_dir=args.cache_dir
        )
    except Exception as e:
        print(f"❌ Failed to initialize GraphRAG system: {e}")
        sys.exit(1)
    
    # Initialize LLM provider if requested
    llm_provider = None
    if args.llm and not args.no_llm:
        llm_provider = create_llm_provider(args.llm)
        if not llm_provider:
            print("⚠️  Continuing without LLM...")
    
    # Handle single query
    if args.query:
        print(f"❓ Question: {args.query}")
        result = graph_rag.query(args.query, llm_provider)
        print_response(result, args.show_context)
        return
    
    # Interactive mode
    if args.interactive:
        print("🎯 Interactive Climate Litigation GraphRAG")
        print("Type 'quit', 'exit', or 'q' to stop")
        print("Type 'help' for available commands\n")
        
        while True:
            try:
                query = input("❓ Your question: ").strip()
                
                if query.lower() in ['quit', 'exit', 'q']:
                    print("👋 Goodbye!")
                    break
                
                if query.lower() == 'help':
                    print("""
📚 Available Commands:
  - Ask any question about climate litigation cases
  - 'stats' - Show system statistics
  - 'examples' - Show example queries
  - 'quit' - Exit the system
                    """)
                    continue
                
                if query.lower() == 'stats':
                    print(f"📊 System Statistics:")
                    print(f"  - Graph nodes: {graph_rag.graph.number_of_nodes()}")
                    print(f"  - Graph edges: {graph_rag.graph.number_of_edges()}")
                    print(f"  - Embeddings cached: {len(graph_rag.node_embeddings)}")
                    if graph_rag.df is not None:
                        print(f"  - Original cases: {len(graph_rag.df)}")
                    print(f"  - LLM provider: {args.llm if llm_provider else 'None'}")
                    continue
                
                if query.lower() == 'examples':
                    print("""
📝 Example Queries:
  Analytical:
    - "Which jurisdictions have the most climate cases?"
    - "How many total cases are there?"
    - "What is the distribution of case statuses?"
    
  Semantic:
    - "Explain the relationship between climate litigation and human rights"
    - "What are the main legal strategies in climate cases?"
    - "Tell me about fossil fuel litigation"
                    """)
                    continue
                
                if not query:
                    continue
                
                result = graph_rag.query(query, llm_provider)
                print_response(result, args.show_context)
                
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error processing query: {e}")

if __name__ == "__main__":
    main()
