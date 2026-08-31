import torch
import torch.nn as nn
import numpy as np
import math
import os

MODEL_DIR = "lstm_models"
os.makedirs(MODEL_DIR, exist_ok=True)

class LSTMAutoencoder(nn.Module):
    def __init__(self, n_features=3, hidden_size=32, seq_len=20):
        super().__init__()
        self.seq_len = seq_len
        self.encoder = nn.LSTM(n_features, hidden_size, batch_first=True)
        self.decoder = nn.LSTM(hidden_size, hidden_size, batch_first=True)
        self.output_layer = nn.Linear(hidden_size, n_features)

    def forward(self, x):
        _, (h, c) = self.encoder(x)
        repeated = h.repeat(self.seq_len, 1, 1).permute(1, 0, 2)
        decoded, _ = self.decoder(repeated)
        return self.output_layer(decoded)


def build_sequences(tick_history, seq_len=20):
    """tick_history: list of tick dicts for ONE ticker, normal (non-scenario) ticks only."""
    if len(tick_history) < seq_len + 5:
        return None
    feats, prev = [], None
    for t in tick_history:
        pct = 0.0 if prev is None else (t["close"] - prev) / prev
        spread = (t["high"] - t["low"]) / t["close"] if t["close"] else 0.0
        feats.append([pct, t["volume"], spread])
        prev = t["close"]
    feats = np.array(feats)
    mean, std = feats.mean(0), feats.std(0) + 1e-6
    feats = (feats - mean) / std
    seqs = [feats[i:i+seq_len] for i in range(len(feats) - seq_len)]
    return torch.tensor(np.array(seqs), dtype=torch.float32), mean, std


def train_and_save(ticker, tick_history, epochs=30, lr=1e-3):
    data = build_sequences(tick_history)
    if data is None:
        return False
    seqs, mean, std = data
    model = LSTMAutoencoder(n_features=3, seq_len=seqs.shape[1])
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.MSELoss()
    model.train()
    for epoch in range(epochs):
        optimizer.zero_grad()
        recon = model(seqs)
        loss = loss_fn(recon, seqs)
        loss.backward()
        optimizer.step()
    model.eval()
    with torch.no_grad():
        recon = model(seqs)
        errors = ((recon - seqs) ** 2).mean(dim=(1, 2)).numpy()
    threshold = float(errors.mean() + 2 * errors.std())

    torch.save({
        "state_dict": model.state_dict(),
        "mean": mean, "std": std, "threshold": threshold, "seq_len": seqs.shape[1]
    }, f"{MODEL_DIR}/{ticker}.pt")
    return True


_loaded_models = {}

def _load(ticker):
    if ticker in _loaded_models:
        return _loaded_models[ticker]
    path = f"{MODEL_DIR}/{ticker}.pt"
    if not os.path.exists(path):
        return None
    checkpoint = torch.load(path, weights_only=False)
    model = LSTMAutoencoder(n_features=3, seq_len=checkpoint["seq_len"])
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    result = (model, checkpoint["mean"], checkpoint["std"], checkpoint["threshold"])
    _loaded_models[ticker] = result
    return result


def lstm_anomaly_score(ticker, recent_ticks):
    loaded = _load(ticker)
    if loaded is None:
        return 0.0
    model, mean, std, threshold = loaded
    if len(recent_ticks) < model.seq_len:
        return 0.0
    window = recent_ticks[-model.seq_len:]
    feats, prev = [], None
    for t in window:
        pct = 0.0 if prev is None else (t["close"] - prev) / prev
        spread = (t["high"] - t["low"]) / t["close"] if t["close"] else 0.0
        feats.append([pct, t["volume"], spread])
        prev = t["close"]
    feats = (np.array(feats) - mean) / std
    x = torch.tensor(feats, dtype=torch.float32).unsqueeze(0)
    with torch.no_grad():
        recon = model(x)
        error = float(((recon - x) ** 2).mean())
    ratio = error / threshold
    return round(min(100.0, 30 * math.log2(1 + max(0, ratio))), 2)