"""
VWAP (Volume-Weighted Average Price) deviation detector.

Industry-standard, deterministic, rule-based check — independent of the ML
ensemble (isolation forest / LSTM / GNN / FinBERT). Flags when the current
price deviates sharply from the volume-weighted average of the last `window`
ticks for that ticker, a classic signal used by real trading surveillance
desks to catch abnormal price action relative to traded volume.
"""
from collections import defaultdict

_vwap_history = defaultdict(list)


def vwap_deviation_score(ticker, price, volume, window=20):
    hist = _vwap_history[ticker]
    hist.append((price, volume))
    if len(hist) > window:
        hist.pop(0)
    if len(hist) < 5:
        return 0.0
    total_vol = sum(v for _, v in hist)
    vwap = (sum(p * v for p, v in hist) / total_vol) if total_vol else price
    deviation_pct = abs(price - vwap) / vwap * 100 if vwap else 0
    return round(min(100.0, deviation_pct * 8), 2)
