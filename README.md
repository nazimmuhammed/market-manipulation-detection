# Market Manipulation Detection & Insider Trading Prevention System

AI-driven financial surveillance platform that detects insider trading and market manipulation (pump-and-dump, spoofing, layering) using a multi-modal ensemble of Isolation Forest, LSTM Autoencoders, Graph Neural Networks, and FinBERT sentiment analysis on real-time NSE stock data.

## Setup Instructions

### Prerequisites
- Python 3.10+
- Node.js 18+

### Backend Setup
1. `cd backend`
2. Create virtual environment: `python -m venv venv`
3. Activate it:
   - Windows: `venv\Scripts\Activate.ps1`
   - Mac/Linux: `source venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Copy `.env.example` to `.env` and fill in your own credentials (Gmail App Password, Twelve Data API key)
6. Run: `uvicorn app.main:app --reload --port 8000`

### Frontend Setup
1. `cd frontend`
2. Install dependencies: `npm install`
3. Run: `npm run dev`
4. Open `http://localhost:5173`

### Notes
- Postgres/Neo4j are optional — the app automatically falls back to SQLite / an in-memory trader graph if they're not running locally, so it works out of the box without Docker.
- On first run, inject a few scenarios and click "Fast Forward" a couple times to warm up the ML models (LSTM/GNN need some baseline data to train on) before demoing.
- Never commit your `.env` file — it's already excluded via `.gitignore`.

## Features
- Real-time price simulation blended with live Twelve Data API feed
- Multi-model risk scoring: Isolation Forest, LSTM Autoencoder, Graph Neural Network, FinBERT sentiment
- Supervised RandomForest classifier trained on confirmed alert patterns
- Automated email reporting and complaint filing via Gmail SMTP
- Explainability layer (why/immediate issue/recommended action per alert, model contribution breakdown)
- Trader network visualization and wash-trading detection
- Live news feed integration via Google News RSS
- Dashboard tabs: Model Comparison, Evaluation Metrics, Trader Reputation, News Feed