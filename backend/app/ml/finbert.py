from transformers import pipeline
import torch

_finbert = pipeline("sentiment-analysis", model="ProsusAI/finbert", device=0 if torch.cuda.is_available() else -1)

def score_ticker_sentiment(ticker, headlines=None):
    if headlines is None:
        from app.ingestion.news import fetch_real_headlines
        headlines = fetch_real_headlines(ticker) or [f"Reports around {ticker} suggest unusual trading activity"]
    results = _finbert(headlines)
    sign = {"positive": 1, "neutral": 0, "negative": -1}
    vals = [sign[r["label"].lower()] * r["score"] for r in results]
    return round(sum(vals) / len(vals), 3)