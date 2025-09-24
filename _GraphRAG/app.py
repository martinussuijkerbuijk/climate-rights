#!/usr/bin/env python3
"""
Flask Web Application for Climate Litigation GraphRAG System
Provides a web interface for the GraphRAG command-line tool.

Usage:
    python app.py
    
Then navigate to: http://localhost:8080
"""

from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
import os
import sys
import json
import traceback
from datetime import datetime
import logging

# Import your GraphRAG system
from graphRAG_cli_FAISS import ClimateGraphRAG, create_llm_provider

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Global variables to store the initialized system
graph_rag = None
llm_provider = None

def clean_for_json(data):
    """
    Recursively clean data structure to make it JSON serializable.
    Removes NetworkX Graph objects and other non-serializable items.
    """
    if isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            # Skip NetworkX Graph objects
            if key == 'subgraph' and hasattr(value, 'nodes'):
                continue
            # Skip other problematic objects
            elif key == 'semantic_results' and isinstance(value, list):
                # Keep only the first few results and convert tuples to lists
                cleaned[key] = [[node_id, float(score)] for node_id, score in value[:5]]
            else:
                cleaned[key] = clean_for_json(value)
        return cleaned
    elif isinstance(data, list):
        return [clean_for_json(item) for item in data]
    elif isinstance(data, tuple):
        return list(data)
    elif hasattr(data, '__dict__') and not isinstance(data, (str, int, float, bool, type(None))):
        # Skip complex objects that can't be serialized
        return str(data)
    else:
        return data


def initialize_system():
    """Initialize the GraphRAG system on startup."""
    global graph_rag, llm_provider
    
    # Configuration - adjust these paths as needed
    GRAPH_JSON_PATH = 'KG-climate-cases/data/knowledge_graph.json'
    CSV_DATA_PATH = '_DATA/GLOBAL_cases_with_topics_named.csv'
    CACHE_DIR = '_cache'
    
    # Default LLM provider (you can change this)
    DEFAULT_LLM = 'gemini'  # or 'gemini' or None
    
    try:
        logger.info("Initializing Climate GraphRAG system...")
        
        # Initialize the GraphRAG system
        graph_rag = ClimateGraphRAG(
            graph_json_path=GRAPH_JSON_PATH,
            original_csv_path=CSV_DATA_PATH if os.path.exists(CSV_DATA_PATH) else None,
            cache_dir=CACHE_DIR
        )
        
        # Initialize LLM provider if configured
        if DEFAULT_LLM:
            try:
                llm_provider = create_llm_provider(DEFAULT_LLM)
                if llm_provider:
                    logger.info(f"LLM provider '{DEFAULT_LLM}' initialized successfully")
                else:
                    logger.warning(f"Failed to initialize LLM provider '{DEFAULT_LLM}'")
            except Exception as e:
                logger.warning(f"LLM initialization failed: {e}")
                llm_provider = None
        
        logger.info("GraphRAG system initialized successfully!")
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize GraphRAG system: {e}")
        logger.error(traceback.format_exc())
        return False

@app.route('/')
def index():
    """Serve the main HTML page."""
    return send_from_directory('.', 'index.html')

@app.route('/style.css')
def styles():
    """Serve the CSS file."""
    return send_from_directory('.', 'style.css')

@app.route('/Climate_Rights_Logo-b1-02.png')
def logo():
    """Serve the logo image."""
    return send_from_directory('.', 'Climate_Rights_Logo-b1-02.png')

@app.route('/query', methods=['POST'])
def handle_query():
    """Handle GraphRAG queries from the web interface."""
    global graph_rag, llm_provider
    
    try:
        # Check if system is initialized
        if graph_rag is None:
            return jsonify({
                'error': 'GraphRAG system not initialized',
                'classification': {'type': 'error', 'confidence': 0.0},
                'answer': 'System initialization failed. Please check server logs.'
            }), 500
        
        # Get the query from the request
        data = request.get_json()
        if not data or 'query' not in data:
            return jsonify({
                'error': 'No query provided',
                'classification': {'type': 'error', 'confidence': 0.0},
                'answer': 'Please provide a query in the request body.'
            }), 400
        
        query_text = data['query'].strip()
        if not query_text:
            return jsonify({
                'error': 'Empty query',
                'classification': {'type': 'error', 'confidence': 0.0},
                'answer': 'Query cannot be empty.'
            }), 400
        
        logger.info(f"Processing query: {query_text}")
        
        # Process the query using the GraphRAG system
        start_time = datetime.now()
        result = graph_rag.query(query_text, llm_provider)
        end_time = datetime.now()
        
        # Clean the result to make it JSON serializable
        cleaned_result = clean_for_json(result)
        
        # Add timing information
        cleaned_result['processing_time'] = (end_time - start_time).total_seconds()
        cleaned_result['timestamp'] = end_time.isoformat()
        
        logger.info(f"Query processed in {cleaned_result['processing_time']:.2f} seconds")
        
        return jsonify(cleaned_result)
        
    except Exception as e:
        logger.error(f"Error processing query: {e}")
        logger.error(traceback.format_exc())
        
        return jsonify({
            'error': str(e),
            'classification': {'type': 'error', 'confidence': 0.0},
            'answer': f'An error occurred while processing your query: {str(e)}'
        }), 500

@app.route('/status', methods=['GET'])
def system_status():
    """Get the status of the GraphRAG system."""
    global graph_rag, llm_provider
    
    status = {
        'system_initialized': graph_rag is not None,
        'llm_provider_available': llm_provider is not None,
        'timestamp': datetime.now().isoformat()
    }
    
    if graph_rag:
        status.update({
            'graph_nodes': graph_rag.graph.number_of_nodes(),
            'graph_edges': graph_rag.graph.number_of_edges(),
            'embeddings_cached': len(graph_rag.node_embeddings),
            'original_data_loaded': graph_rag.df is not None
        })
        
        if graph_rag.df is not None:
            status['total_cases'] = len(graph_rag.df)
    
    return jsonify(status)

@app.route('/examples', methods=['GET'])
def get_examples():
    """Get example queries for the interface."""
    examples = {
        'analytical': [
            "Which jurisdictions have the most climate cases?",
            "How many total cases are there?",
            "What is the distribution of case statuses?",
            "Which years had the most climate litigation filings?"
        ],
        'semantic': [
            "Explain the relationship between climate litigation and human rights",
            "What are the main legal strategies in climate cases?",
            "Tell me about fossil fuel litigation",
            "How do climate cases address adaptation vs mitigation?",
            "What role do youth play in climate litigation?"
        ],
        'hybrid': [
            "What are the top climate litigation topics and which jurisdictions address them most?",
            "How has climate litigation evolved over time and what are the key themes?",
            "Compare the legal approaches across different jurisdictions"
        ]
    }
    
    return jsonify(examples)

@app.route('/config', methods=['GET'])
def get_config():
    """Get current system configuration."""
    global llm_provider
    
    config = {
        'llm_provider': type(llm_provider).__name__ if llm_provider else None,
        'embedding_model': graph_rag.embedding_model_name if graph_rag else None,
        'cache_enabled': True,
        'version': "1.0.0"
    }
    
    return jsonify(config)

@app.route('/switch_llm', methods=['POST'])
def switch_llm():
    """Switch LLM provider at runtime."""
    global llm_provider
    
    try:
        data = request.get_json()
        provider_name = data.get('provider', '').lower()
        
        if provider_name == 'none':
            llm_provider = None
            return jsonify({
                'success': True,
                'message': 'LLM provider disabled',
                'current_provider': None
            })
        
        if provider_name not in ['openai', 'gemini']:
            return jsonify({
                'success': False,
                'error': 'Invalid provider. Use "openai", "gemini", or "none"'
            }), 400
        
        new_provider = create_llm_provider(provider_name)
        if new_provider:
            llm_provider = new_provider
            return jsonify({
                'success': True,
                'message': f'Switched to {provider_name}',
                'current_provider': provider_name
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Failed to initialize {provider_name} provider'
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return jsonify({
        'error': 'Endpoint not found',
        'available_endpoints': [
            '/ - Main interface',
            '/query - Submit queries',
            '/status - System status',
            '/examples - Example queries',
            '/config - System configuration'
        ]
    }), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    logger.error(f"Internal server error: {error}")
    return jsonify({
        'error': 'Internal server error',
        'message': 'An unexpected error occurred. Please check server logs.'
    }), 500

def check_dependencies():
    """Check if all required dependencies are available."""
    missing_deps = []
    
    try:
        import flask
    except ImportError:
        missing_deps.append('flask')
    
    try:
        import flask_cors
    except ImportError:
        missing_deps.append('flask-cors')
    
    # Check if the GraphRAG module can be imported
    try:
        from graphRAG_cli import ClimateGraphRAG
    except ImportError:
        missing_deps.append('graphRAG_cli (ensure the file is in the same directory)')
    
    return missing_deps

if __name__ == '__main__':
    print("🌍 Climate Litigation GraphRAG Web Application")
    print("=" * 50)
    
    # Check dependencies
    missing_deps = check_dependencies()
    if missing_deps:
        print(f"❌ Missing dependencies: {', '.join(missing_deps)}")
        print("Install with: pip install flask flask-cors")
        sys.exit(1)
    
    # Initialize the GraphRAG system
    print("🚀 Initializing GraphRAG system...")
    if not initialize_system():
        print("❌ Failed to initialize GraphRAG system. Check configuration.")
        sys.exit(1)
    
    print("✅ System initialized successfully!")
    print("\n📋 System Information:")
    if graph_rag:
        print(f"  • Graph nodes: {graph_rag.graph.number_of_nodes()}")
        print(f"  • Graph edges: {graph_rag.graph.number_of_edges()}")
        print(f"  • Embeddings cached: {len(graph_rag.node_embeddings)}")
        if graph_rag.df is not None:
            print(f"  • Total cases: {len(graph_rag.df)}")
    
    if llm_provider:
        print(f"  • LLM provider: {type(llm_provider).__name__}")
    else:
        print("  • LLM provider: None (context-only mode)")
    
    print(f"\n🌐 Starting web server...")
    print("🔗 Access the application at: http://localhost:5000")
    print("📚 API endpoints:")
    print("   • POST /query - Submit queries")
    print("   • GET /status - System status")
    print("   • GET /examples - Example queries")
    print("   • GET /config - System configuration")
    print("   • POST /switch_llm - Change LLM provider")
    print("\n📱 Press Ctrl+C to stop the server")
    print("=" * 50)
    
    # Run the Flask application
    app.run(
        host='10.24.36.19',  # Allow external connections
        port=8080,
        debug=False,  # Set to True for development
        use_reloader=False  # Prevent double initialization
    )