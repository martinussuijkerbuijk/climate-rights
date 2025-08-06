import os
import pandas as pd
import json
from bertopic import BERTopic

def create_topic_graph(csv_path, issue_column, output_path):
    """
    Uses BERTopic to perform topic modeling on climate issues and generates
    a hierarchical graph data structure for visualization.

    Args:
        csv_path (str): Path to the input CSV file with extracted issues.
        issue_column (str): The column containing the text to analyze.
        output_path (str): Path to save the output JSON file.
    """
    # --- 1. Load Data ---
    if not os.path.exists(csv_path):
        print(f"Error: Input file not found at '{csv_path}'")
        return

    print(f"Reading data from '{csv_path}'...")
    df = pd.read_csv(csv_path)
    
    # Ensure the issue column is clean and in list format for BERTopic
    # We drop any rows where the issue might be missing
    df.dropna(subset=[issue_column], inplace=True)
    issues = df[issue_column].tolist()
    
    print(f"Found {len(issues)} issues to model.")

    # --- 2. Perform Topic Modeling with BERTopic ---
    print("Initializing and running BERTopic model... (This may take a few minutes)")
    
    # By setting `min_topic_size`, we force smaller, similar topics to merge,
    # creating more coherent and distinct topics.
    topic_model = BERTopic(
        embedding_model="all-MiniLM-L6-v2", 
        verbose=True,
        min_topic_size=5  # A topic must have at least 5 documents
    )
    
    # Fit the model and get the topic for each issue
    topics, _ = topic_model.fit_transform(issues)
    
    # Add the topic number to our original DataFrame
    df['topic'] = topics
    
    print("Topic modeling complete.")

    # --- 3. Structure Graph Data ---
    print("Structuring data for the knowledge graph...")
    nodes = []
    links = []
    
    # Create a set to avoid duplicate nodes
    node_set = set()

    # Get information about the discovered topics (names, size)
    topic_info = topic_model.get_topic_info()

    # Create a main node for each topic
    for index, row in topic_info.iterrows():
        topic_id = row['Topic']
        # Skip the outlier topic (-1) which contains uncategorized issues
        if topic_id == -1:
            continue
            
        # Create a clean topic name without the "Topic X:" prefix
        topic_name = row['Name'].replace('_', ' ')
        
        nodes.append({
            "id": topic_name,
            "type": "topic",
            "count": row['Count']
        })
        node_set.add(topic_name)

    # Create a leaf node for each unique issue and link it to its topic
    for _, row in df.iterrows():
        topic_id = row['topic']
        if topic_id == -1:
            continue

        issue_text = row[issue_column]
        topic_info_row = topic_info[topic_info['Topic'] == topic_id].iloc[0]
        # Use the clean topic name for linking
        topic_name = topic_info_row['Name'].replace('_', ' ')

        # Add the issue as a node if it hasn't been added yet
        if issue_text not in node_set:
            nodes.append({
                "id": issue_text,
                "type": "issue",
                "count": 1 # Each issue node has a base size
            })
            node_set.add(issue_text)
        
        # Create a link from the issue to its parent topic
        links.append({
            "source": issue_text,
            "target": topic_name,
            "weight": 1 # Base weight for all links
        })

    graph_data = {"nodes": nodes, "links": links}

    # --- 4. Save to JSON ---
    print(f"Saving new graph data to '{output_path}'...")
    with open(output_path, 'w') as f:
        json.dump(graph_data, f, indent=2)
    print("Done.")


# --- How to Use ---
if __name__ == '__main__':
    # --- Configuration ---
    # 1. Path to your CSV file with the extracted issues.
    CSV_INPUT_PATH = 'G:/My Drive/PostDoc/BA/_MAP/_DATA/cases_with_extracted_issues.csv'
    
    # 2. Name of the column with the issues.
    ISSUE_COLUMN_NAME = 'Extracted Climate Issue'
    
    # 3. Path for the output JSON file.
    JSON_OUTPUT_PATH = 'D:/_POSTDOC/_CR/_BA/_MAP/knowledge-graph/public/graph_data.json'
    # -------------------

    create_topic_graph(
        csv_path=CSV_INPUT_PATH,
        issue_column=ISSUE_COLUMN_NAME,
        output_path=JSON_OUTPUT_PATH
    )
