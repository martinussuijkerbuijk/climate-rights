import pandas as pd
import spacy
import logging
import joblib  # <--- Added for saving the Label Encoder
import os
from typing import List, Dict, Tuple, Union
from sklearn.preprocessing import MultiLabelBinarizer
from datasets import Dataset
from setfit import SetFitModel, SetFitTrainer
from sentence_transformers import SentenceTransformer, util
from sentence_transformers.losses import CosineSimilarityLoss
import torch

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ClimateLitigationAgent:
    """
    An AI Agent capable of analyzing climate litigation texts.
    Now supports SAVING and LOADING to avoid retraining.
    """

    def __init__(self, embedding_model_name: str = "all-MiniLM-L6-v2", model_dir: str = "climate_agent_artifacts"):
        """
        Args:
            embedding_model_name: HuggingFace model ID for embeddings (used for Law Retrieval).
            model_dir: Directory to save/load the trained classification model.
        """
        logger.info("Initializing ClimateLitigationAgent...")
        
        self.model_dir = model_dir
        self.classifier_path = os.path.join(model_dir, "category_classifier")
        self.encoder_path = os.path.join(model_dir, "label_binarizer.joblib")

        # Load NLP model for cleaning
        try:
            self.nlp = spacy.load("en_core_web_sm")
        except OSError:
            logger.warning("Spacy model not found. Downloading en_core_web_sm...")
            from spacy.cli import download
            download("en_core_web_sm")
            self.nlp = spacy.load("en_core_web_sm")

        # Load Embedding Model for Law Retrieval (RAG)
        self.embedding_model = SentenceTransformer(embedding_model_name)
        
        # Components
        self.category_model = None
        self.category_binarizer = None 
        self.law_embeddings = None
        self.law_list = [] 

        # Attempt to load existing model on startup
        if os.path.exists(self.classifier_path) and os.path.exists(self.encoder_path):
            self.load_resources()

    def clean_text(self, text: str) -> str:
        if not isinstance(text, str): return ""
        doc = self.nlp(text)
        tokens = [token.lemma_ for token in doc if not token.is_stop and not token.is_punct and len(token.text) > 2]
        return " ".join(tokens)

    def parse_list_column(self, text: str, separator: str = '|') -> List[str]:
        if pd.isna(text): return []
        text = text.replace('>', '|') 
        items = [item.strip() for item in text.split(separator)]
        return [item for item in items if item]

    def load_and_prepare_data(self, filepath: str) -> pd.DataFrame:
        logger.info(f"Loading data from {filepath}...")
        df = pd.read_csv(filepath)
        df['clean_description'] = df['Description'].apply(self.clean_text)
        df['parsed_categories'] = df['Case Categories'].apply(lambda x: self.parse_list_column(x, separator='|'))
        df['parsed_laws'] = df['Principal Laws'].apply(lambda x: self.parse_list_column(x, separator='|'))
        return df

    def train_category_classifier(self, df: pd.DataFrame):
        """
        Trains (or Retrains) the SetFit model and SAVES it to disk.
        """
        logger.info("Training Case Category Classifier (SetFit)...")
        
        # 1. Encode Labels (and SAVE the encoder!)
        self.category_binarizer = MultiLabelBinarizer()
        y_matrix = self.category_binarizer.fit_transform(df['parsed_categories'])
        
        # Save the binarizer (Crucial: maps [1,0] back to "Environmental Assessment")
        os.makedirs(self.model_dir, exist_ok=True)
        joblib.dump(self.category_binarizer, self.encoder_path)
        logger.info(f"Label Encoder saved to {self.encoder_path}")
        
        # 2. Prepare Dataset
        train_dataset = Dataset.from_dict({
            "text": df['clean_description'].tolist(),
            "label": y_matrix
        })
        
        # 3. Train
        model = SetFitModel.from_pretrained("sentence-transformers/paraphrase-mpnet-base-v2", multi_target_strategy="one-vs-rest")
        
        trainer = SetFitTrainer(
            model=model,
            train_dataset=train_dataset,
            loss_class=CosineSimilarityLoss,
            metric="accuracy",
            batch_size=16,
            num_iterations=5, 
            num_epochs=1
        )
        
        trainer.train()
        
        # 4. Save Model
        self.category_model = model
        model.save_pretrained(self.classifier_path)
        logger.info(f"Category Model saved to {self.classifier_path}")

    def load_resources(self):
        """
        Loads the trained model and encoder from disk.
        """
        logger.info("Loading pre-trained resources from disk...")
        try:
            self.category_model = SetFitModel.from_pretrained(self.classifier_path)
            self.category_binarizer = joblib.load(self.encoder_path)
            logger.info("✅ Model and Encoder loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            self.category_model = None

    def build_law_retrieval_index(self, df: pd.DataFrame):
        logger.info("Building Law Retrieval Index...")
        all_laws = set()
        for law_list in df['parsed_laws']:
            for law in law_list:
                all_laws.add(law)
        self.law_list = list(all_laws)
        if self.law_list:
            self.law_embeddings = self.embedding_model.encode(self.law_list, convert_to_tensor=True)
        else:
            logger.warning("No laws found to index.")

    def predict(self, description: str, top_k_laws: int = 3) -> Dict[str, Union[List[str], float]]:
        if not description: return {"error": "Empty description"}
        clean_desc = self.clean_text(description)
        
        results = {"original_text": description, "predicted_categories": [], "suggested_laws": []}

        # 1. Predict Categories
        if self.category_model and self.category_binarizer:
            preds = self.category_model.predict([clean_desc])
            try:
                # Decode binary vector back to strings
                predicted_labels = self.category_binarizer.inverse_transform(preds.cpu().numpy())
                results["predicted_categories"] = [label for label in predicted_labels[0]]
            except Exception as e:
                logger.error(f"Error decoding categories: {e}")
        else:
            results["predicted_categories"] = ["Model not loaded/trained"]

        # 2. Predict Laws
        if self.law_embeddings is not None:
            query_embedding = self.embedding_model.encode(clean_desc, convert_to_tensor=True)
            hits = util.semantic_search(query_embedding, self.law_embeddings, top_k=top_k_laws)
            for hit in hits[0]:
                if hit['score'] > 0.25:
                    results["suggested_laws"].append({
                        "law": self.law_list[hit['corpus_id']],
                        "confidence": round(hit['score'], 3)
                    })
        else:
            results["suggested_laws"] = ["Index not built"]

        return results

# ==========================================
# MAIN EXECUTION BLOCK
# ==========================================
if __name__ == "__main__":
    # 1. Setup
    agent = ClimateLitigationAgent(model_dir="climate_agent_artifacts")
    
    # Check if model exists
    model_exists = os.path.exists(agent.classifier_path)
    
    # 2. Create Dummy Data (Only needed if training)
    data = {
        "Case Name": ["Turramurra v. Council", "Haughton v. Minister", "FutureGen v. EPA"],
        "Description": [
            "Applicant appealed the denial of a permit for a residential development due to risk of fire. Council cited climate change increasing fire risk.",
            "Challenge to government approval of two coal-fired power plants. Claimed minister failed to consider climate impact.",
            "NGO sued the EPA for failing to regulate carbon emissions from new factories, claiming it violates the Clean Air Act."
        ],
        "Case Categories": [
            "Suits Against Governments>Climate Adaptation",
            "Suits Against Governments>Environmental Assessment",
            "Suits Against Governments>Clean Air Claims"
        ],
        "Principal Laws": [
            "Environmental Planning and Assessment Act 1979 (NSW)",
            "Environmental Planning and Assessment Act 1979 (NSW)|Precautionary Principle",
            "Clean Air Act|National Environmental Policy Act"
        ]
    }
    dummy_csv_name = "./Data/CASES_COMBINED_status.csv"
    # df_dummy = pd.DataFrame(data)
    # df_dummy.to_csv(dummy_csv_name, index=False)
    
    df_processed = agent.load_and_prepare_data(dummy_csv_name)

    # 3. Train OR Load
    if not model_exists:
        print("\n🚀 No saved model found. Training new model...")
        agent.train_category_classifier(df_processed)
    else:
        print("\n💾 Saved model found. Loading from disk (Skipping training)...")
        # Note: agent.__init__ already tried to load it, but we can ensure it's loaded
        if agent.category_model is None:
            agent.load_resources()

    # 4. Always rebuild Law Index (Fast, usually done on startup in memory)
    # In a real app, you would also save/load the law embeddings via pickle/joblib
    agent.build_law_retrieval_index(df_processed)
    
    # 5. Test
    # test_text = "A local group in California is suing the city for approving a new highway that will increase emissions."
    test_text = "Applicants challenged a redevelopment proposal because of failure to conduct a coastal hazard vulnerability assessment"
    print(f"\n--- TESTING PREDICTION ---")
    print(f"Query: {test_text}")
    prediction = agent.predict(test_text)
    print("Categories:", prediction["predicted_categories"])
    print("Laws:", prediction["suggested_laws"])

    # if os.path.exists(dummy_csv_name): os.remove(dummy_csv_name)

    ##########################################
    ###########  NEXT STEPS   ################
    # 1. Improve accuracy
    # 2. Show the connection between the principle laws. This can be a graph structure.
    # 3. Predict "CaseCategory" from description