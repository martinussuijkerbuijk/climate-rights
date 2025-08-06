import os
import pandas as pd
import json
from bertopic import BERTopic

def create_topic_graph(csv_path, issue_column, case_name_column, summary_column, year_column, status_column, output_path):
    """
    Uses BERTopic to perform topic modeling on climate issues and generates
    a hierarchical graph data structure linking topics to case names with extra details.

    Args:
        csv_path (str): Path to the input CSV file.
        issue_column (str): The column containing the text to analyze for topics.
        case_name_column (str): The column containing the case names for the nodes.
        summary_column (str): The column containing the case summary.
        year_column (str): The column containing the case filing year.
        status_column (str): The column containing the case status.
        output_path (str): Path to save the output JSON file.
    """
    # --- 1. Load Data ---
    if not os.path.exists(csv_path):
        print(f"Error: Input file not found at '{csv_path}'")
        return

    print(f"Reading data from '{csv_path}'...")
    df = pd.read_csv(csv_path)
    
    # Define all required columns
    required_columns = [issue_column, case_name_column, summary_column, year_column, status_column]
    
    # Check for required columns
    if not all(col in df.columns for col in required_columns):
        print(f"Error: Ensure all required columns exist in the CSV: {required_columns}")
        return

    # Drop rows where any of the required data is missing
    df.dropna(subset=required_columns, inplace=True)
    issues = df[issue_column].tolist()
    
    print(f"Found {len(issues)} issues to model.")

    # --- 2. Perform Topic Modeling with BERTopic ---
    print("Initializing and running BERTopic model... (This may take a few minutes)")
    
    topic_model = BERTopic(
        embedding_model="all-MiniLM-L6-v2", 
        verbose=True,
        min_topic_size=5
    )
    
    topics, _ = topic_model.fit_transform(issues)
    df['topic'] = topics
    
    print("Topic modeling complete.")

    # --- 3. Structure Graph Data ---
    print("Structuring data for the knowledge graph...")
    nodes = []
    links = []
    node_set = set()

    topic_info = topic_model.get_topic_info()

    # Create a main node for each topic
    for index, row in topic_info.iterrows():
        topic_id = row['Topic']
        if topic_id == -1:
            continue
            
        topic_name = row['Name'].replace('_', ' ')
        
        nodes.append({
            "id": topic_name,
            "type": "topic",
            "count": row['Count']
        })
        node_set.add(topic_name)

    # Create a leaf node for each CASE NAME and link it to its topic
    for _, row in df.iterrows():
        topic_id = row['topic']
        if topic_id == -1:
            continue

        case_name = row[case_name_column]
        topic_info_row = topic_info[topic_info['Topic'] == topic_id].iloc[0]
        topic_name = topic_info_row['Name'].replace('_', ' ')

        # Add the case as a node if it hasn't been added yet
        if case_name not in node_set:
            nodes.append({
                "id": case_name,
                "type": "case",
                "count": 1, # Base size for case nodes
                # Add the extra data for the tooltip
                "summary": row[summary_column],
                "year": row[year_column],
                "status": row[status_column]
            })
            node_set.add(case_name)
        
        # Create a link from the case to its parent topic
        links.append({
            "source": case_name,
            "target": topic_name,
            "weight": 1
        })

    graph_data = {"nodes": nodes, "links": links}

    # --- 4. Save to JSON ---
    print(f"Saving new graph data to '{output_path}'...")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(graph_data, f, indent=2, ensure_ascii=False)
    print("Done.")


# --- How to Use ---
if __name__ == '__main__':
    # --- Configuration ---
    # 1. Path to your CSV file with the extracted issues.
    CSV_INPUT_PATH = 'G:/My Drive/PostDoc/BA/_MAP/_DATA/cases_with_extracted_issues.csv'
    
    # 2. Name of the column with the issues (used for analysis).
    ISSUE_COLUMN_NAME = 'Extracted Climate Issue'
    
    # 3. Name of the column with the case names (used for nodes).
    CASE_NAME_COLUMN = 'Case Name'

    # 4. Add the names of the columns for the tooltip data.
    SUMMARY_COLUMN_NAME = 'Summary'
    YEAR_COLUMN_NAME = 'Filing Year for Action'
    STATUS_COLUMN_NAME = 'Status'
    
    # 5. Path for the output JSON file.
    JSON_OUTPUT_PATH = 'D:/_POSTDOC/_CR/_BA/_MAP/knowledge-graph/public/graph_data.json'
    # -------------------

    create_topic_graph(
        csv_path=CSV_INPUT_PATH,
        issue_column=ISSUE_COLUMN_NAME,
        case_name_column=CASE_NAME_COLUMN,
        summary_column=SUMMARY_COLUMN_NAME,
        year_column=YEAR_COLUMN_NAME,
        status_column=STATUS_COLUMN_NAME,
        output_path=JSON_OUTPUT_PATH
    )
