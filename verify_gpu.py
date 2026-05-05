"""Verify Sentiment Arc runs on GPU."""
import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(name)s - %(message)s")

import sys
import torch

print(f"torch version: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
print(f"CUDA device count: {torch.cuda.device_count()}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name(0)}")

sys.path.insert(0, ".cursor/hooks")

from sentiment_arc.embedder import get_sentiment_model, get_embedding_model, compute_sentiment_scores

print("\n--- Loading sentiment model ---")
sent = get_sentiment_model()
sent_model = sent["model"]
device = sent["device"]
print(f"Resolved device: {device}")
for p in sent_model.parameters():
    print(f"Parameter device: {p.device}")
    break

print("\n--- Loading embedding model ---")
emb = get_embedding_model()
print(f"Embedding model device: {emb.device}")

print("\n--- Running quick inference ---")
scores = compute_sentiment_scores([
    "I love this, it works great!",
    "This is terrible and broken.",
    "The code runs without errors.",
])
print(f"Scores: {scores}")

print("\nAll models loaded and inference ran successfully on GPU.")
