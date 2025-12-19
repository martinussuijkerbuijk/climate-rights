import pandas as pd
import json

def convert_csv_to_gemini_jsonl(input_csv, train_jsonl, eval_jsonl, eval_count=100):
    """
    Converts a CSV file to Gemini Finetuning JSONL format, splitting into train and eval sets.
    """
    
    # Load the dataset
    try:
        df = pd.read_csv(input_csv, on_bad_lines='skip')
    except FileNotFoundError:
        print(f"Error: The file {input_csv} was not found.")
        return

    # Filter out invalid rows first so our split is accurate on valid data only
    # We create a copy to avoid SettingWithCopy warnings
    df_clean = df.dropna(subset=['Description', 'Case Categories']).copy()
    
    total_rows = len(df_clean)
    
    # Safety check for dataset size
    if total_rows <= eval_count:
        print(f"Error: Dataset size ({total_rows}) is too small for an eval set of {eval_count}.")
        print("Proceeding with converting entire dataset to training file only.")
        train_df = df_clean
        eval_df = pd.DataFrame() # Empty
    else:
        # Create the split
        # random_state=42 ensures the split is reproducible
        eval_df = df_clean.sample(n=eval_count, random_state=42) 
        train_df = df_clean.drop(eval_df.index)

    print(f"Total valid rows: {total_rows}")
    print(f"Training set size: {len(train_df)}")
    print(f"Evaluation set size: {len(eval_df)}")

    # Helper function to write a dataframe to JSONL
    def write_df_to_jsonl(dataframe, filename):
        if dataframe.empty:
            return
            
        with open(filename, 'w', encoding='utf-8') as f:
            for _, row in dataframe.iterrows():
                description = row['Description']
                case_laws = row['Principal Laws'] 
                
                user_text = (
                    f"Analyze the following legal case description and assign the appropriate "
                    f"principal laws that might be violated.\n\nDescription:\n{description}"
                )
                model_text = str(case_laws)
                
                entry = {
                    "contents": [
                        {"role": "user", "parts": [{"text": user_text}]},
                        {"role": "model", "parts": [{"text": model_text}]}
                    ]
                }
                f.write(json.dumps(entry) + '\n')
        print(f"Saved {filename}")

    # Write the files
    write_df_to_jsonl(train_df, train_jsonl)
    if not eval_df.empty:
        write_df_to_jsonl(eval_df, eval_jsonl)

# Run the conversion
convert_csv_to_gemini_jsonl(
    './Data/CASES_COMBINED_status.csv', 
    'gemini_finetune_CC_train.jsonl', 
    'gemini_finetune_CC_eval.jsonl'
)