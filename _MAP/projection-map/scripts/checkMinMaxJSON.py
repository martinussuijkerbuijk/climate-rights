import pandas as pd
import os
import json
import numpy as np

def find_min_max_in_json_files(folder_path):
    """
    Finds the overall minimum and maximum values from a 'values' key
    in all JSON files within a specified folder.

    Also processes each file by dividing all non-zero numeric values by 10000
    and overwrites the original file.

    Args:
        folder_path (str): The path to the folder containing the JSON files.

    Returns:
        tuple: A tuple containing the overall minimum and maximum values from the
               original data, or (None, None) if no valid data is found.
    """
    # Initialize overall min and max with infinity to ensure any actual number will be smaller/larger
    overall_min = float('inf')
    overall_max = float('-inf')
    
    # Check if the directory exists
    if not os.path.isdir(folder_path):
        print(f"Error: Folder not found at '{folder_path}'")
        return None, None

    print(f"Scanning and processing files in '{folder_path}'...")

    # Loop through all files in the given folder
    for filename in os.listdir(folder_path):
        # Check if the file is a JSON file
        if filename.endswith('.json'):
            file_path = os.path.join(folder_path, filename)
            
            try:
                # Open and load the JSON file
                with open(file_path, 'r') as f:
                    data = json.load(f)
                
                # First, find min/max from the original data
                if 'values' in data and isinstance(data['values'], list):
                    values_series = pd.Series(data['values'])
                    numeric_series = pd.to_numeric(values_series, errors='coerce').dropna()
                    
                    if not numeric_series.empty:
                        local_min = numeric_series.min()
                        local_max = numeric_series.max()
                        
                        print(f"File: {filename} -> Original Min: {local_min}, Original Max: {local_max}")
                        
                        if local_min < overall_min:
                            overall_min = local_min
                        if local_max > overall_max:
                            overall_max = local_max
                    else:
                        print(f"File: {filename} -> No valid numeric data found to analyze.")

                    # Now, process the data and save it back
                    processed_values = [
                        v / 10000 if isinstance(v, (int, float)) and v != 0 else v
                        for v in data['values']
                    ]
                    data['values'] = processed_values
                    
                    with open(file_path, 'w') as f:
                        json.dump(data, f)
                    print(f"File: {filename} -> Processed and saved.")

                else:
                     print(f"File: {filename} -> Does not contain a 'values' list. Skipping.")

            except json.JSONDecodeError:
                print(f"Error: Could not decode JSON from {filename}.")
            except Exception as e:
                print(f"An unexpected error occurred with file {filename}: {e}")

    # Check if any values were actually found
    if overall_min == float('inf') or overall_max == float('-inf'):
        print("\nNo numeric values were found in any JSON files.")
        return None, None
    else:
        return overall_min, overall_max

if __name__ == '__main__':
    # --- IMPORTANT ---
    # Change this path to the folder you want to inspect
    path_to_your_folder = 'public/seaLevel' 
    
    min_val, max_val = find_min_max_in_json_files(path_to_your_folder)
    
    if min_val is not None and max_val is not None:
        print("\n-----------------------------------------")
        print(f"Overall Minimum Value (from original data): {min_val}")
        print(f"Overall Maximum Value (from original data): {max_val}")
        print("-----------------------------------------")

