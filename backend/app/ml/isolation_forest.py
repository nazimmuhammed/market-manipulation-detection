import numpy as np
from collections import deque, defaultdict
from sklearn.ensemble import IsolationForest

WINDOW_SIZE, REFIT_EVERY, MIN_SAMPLES = 60, 15, 20

class RollingIsoForest:
    def __init__(self):
        self.history = defaultdict(lambda: deque(maxlen=WINDOW_SIZE))
        self.models = {}
        self.since_refit = defaultdict(int)

    def _features(self, tick, prev_price):
        pct = 0.0 if not prev_price else (tick["close"] - prev_price) / prev_price
        spread = (tick["high"] - tick["low"]) / tick["close"] if tick["close"] else 0.0
        return [pct, tick["volume"], spread]

    def score(self, tick):
        ticker = tick["ticker"]
        hist = self.history[ticker]
        prev_price = hist[-1]["close"] if hist else None
        feats = self._features(tick, prev_price)
        hist.append(tick)
        self.since_refit[ticker] += 1
        if len(hist) < MIN_SAMPLES:
            return 0.0
        if ticker not in self.models or self.since_refit[ticker] >= REFIT_EVERY:
            X = self._matrix(hist)
            m = IsolationForest(n_estimators=100, contamination=0.05, random_state=42)
            m.fit(X)
            self.models[ticker] = m
            self.since_refit[ticker] = 0
        raw = self.models[ticker].decision_function([feats])[0]
        if raw >= 0:
            return 0.0
        return round(float(np.clip(-raw * 300, 0, 100)), 2)

    def _matrix(self, hist):
        rows, prev = [], None
        for t in hist:
            rows.append(self._features(t, prev))
            prev = t["close"]
        return np.array(rows)

iso_scorer = RollingIsoForest()