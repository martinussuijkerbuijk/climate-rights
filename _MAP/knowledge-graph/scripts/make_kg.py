import os
import pandas as pd
import json
import re
from collections import Counter
from itertools import combinations
import nltk
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer
from nltk.tokenize import word_tokenize

def create_graph_data(csv_path, issue_column, output_path, min_node_freq=3):
    """
    Analyzes a CSV column to create a node-link data structure for a knowledge graph.

    Args:
        csv_path (str): Path to the input CSV file.
        issue_column (str): The column containing the text to analyze.
        output_path (str): Path to save the output JSON file.
        min_node_freq (int): The minimum number of times a word must appear to be a node.
    """
    # --- 1. Setup NLP tools ---
    stop_words = set(stopwords.words('english'))
    lemmatizer = WordNetLemmatizer()

    def process_text(text):
        """Cleans and tokenizes text to extract key concepts (lemmas)."""
        if not isinstance(text, str):
            return []
        # Remove non-alphanumeric characters and tokenize
        text = re.sub(r'\W', ' ', text.lower())
        tokens = word_tokenize(text)
        # Lemmatize and remove stop words
        lemmas = [lemmatizer.lemmatize(w) for w in tokens if w not in stop_words and len(w) > 2]
        return lemmas

    # --- 2. Read and Process Data ---
    if not os.path.exists(csv_path):
        print(f"Error: Input file not found at '{csv_path}'")
        return

    print("Reading and processing text from CSV...")
    df = pd.read_csv(csv_path)
    
    # Apply the text processing to each issue
    df['lemmas'] = df[issue_column].apply(process_text)

    # --- 3. Create Nodes (Concepts) ---
    print("Calculating node frequencies...")
    all_lemmas = [lemma for sublist in df['lemmas'] for lemma in sublist]
    node_counts = Counter(all_lemmas)
    
    # Filter nodes by minimum frequency to keep the graph clean
    nodes = [
        {"id": lemma, "count": count}
        for lemma, count in node_counts.items()
        if count >= min_node_freq
    ]
    # Create a set of valid node names for quick lookup
    valid_node_names = {node['id'] for node in nodes}
    print(f"Created {len(nodes)} nodes with a minimum frequency of {min_node_freq}.")

    # --- 4. Create Links (Co-occurrences) ---
    print("Calculating link weights...")
    link_counts = Counter()
    for lemma_list in df['lemmas']:
        # Filter out lemmas that didn't make it into our valid node set
        filtered_lemmas = [lemma for lemma in lemma_list if lemma in valid_node_names]
        # Find all unique pairs of concepts that co-occur in the same issue
        for pair in combinations(sorted(set(filtered_lemmas)), 2):
            link_counts[pair] += 1

    links = [
        {"source": source, "target": target, "weight": weight}
        for (source, target), weight in link_counts.items()
    ]
    print(f"Created {len(links)} links.")

    # --- 5. Save to JSON ---
    graph_data = {"nodes": nodes, "links": links}
    
    print(f"Saving graph data to '{output_path}'...")
    with open(output_path, 'w') as f:
        json.dump(graph_data, f, indent=2)
    print("Done.")

# --- How to Use ---
if __name__ == '__main__':
    # --- Configuration ---
    # 1. Path to your CSV file with the extracted issues.
    CSV_INPUT_PATH = './_DATA/cases_with_extracted_issues.csv'
    
    # 2. Name of the column with the issues.
    ISSUE_COLUMN_NAME = 'Extracted Climate Issue'
    
    # 3. Path for the output JSON file. This will be used by the HTML/JS file.
    JSON_OUTPUT_PATH = 'graph_data.json'
    
    # 4. Minimum frequency for a concept to be included in the graph.
    #    Helps to remove noise from very rare terms.
    MINIMUM_NODE_FREQUENCY = 3
    # -------------------

    create_graph_data(
        csv_path=CSV_INPUT_PATH,
        issue_column=ISSUE_COLUMN_NAME,
        output_path=JSON_OUTPUT_PATH,
        min_node_freq=MINIMUM_NODE_FREQUENCY
    )
