"""
Volume spike detector using a rolling z-score.

A second, purely statistical detector (no ML training needed) — flags when
traded volume for a tick is an abnormal number of standard deviations above
the recent rolling mean for that ticker. Sudden unexplained volume spikes are
a classic precursor/companion signal to pump-and-dump and spoofing activity.
"""
import math
from collections import defaultdict

_volume_history = defaultdict(list)


def volume_zscore_score(ticker, volume, window=30):
    hist = _volume_history[ticker]
    hist.append(volume)
    if len(hist) > window:
        hist.pop(0)
    if len(hist) < 8:
        return 0.0
    mean = sum(hist) / len(hist)
    variance = sum((v - mean) ** 2 for v in hist) / len(hist)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    z = (volume - mean) / std
    # only unusually HIGH volume is suspicious, not low volume
    if z <= 0:
        return 0.0
    return round(min(100.0, z * 20), 2)
