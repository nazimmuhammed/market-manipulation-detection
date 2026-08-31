"""
Plugin registry - auto-discovers every Detector subclass living in this
folder (except base.py / __init__.py) and exposes run_all() so the risk
scorer can call every registered plugin without knowing they exist.
"""
import importlib
import inspect
import pkgutil
from collections import defaultdict

from app.ml.plugins.base import Detector

_registered = {}          # name -> instance
_last_scores = defaultdict(dict)  # ticker -> {plugin_name: score}


def _discover():
    if _registered:
        return
    package = __name__
    pkg_path = __path__
    for _, mod_name, is_pkg in pkgutil.iter_modules(pkg_path):
        if is_pkg or mod_name in ("base",):
            continue
        try:
            module = importlib.import_module(f"{package}.{mod_name}")
        except Exception as e:
            print(f"[plugins] failed to import {mod_name}: {e}")
            continue
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, Detector) and obj is not Detector:
                try:
                    inst = obj()
                    _registered[inst.name] = inst
                    print(f"[plugins] loaded detector: {inst.name}")
                except Exception as e:
                    print(f"[plugins] failed to instantiate {obj}: {e}")


def list_plugins():
    _discover()
    return [{"name": p.name, "description": p.description} for p in _registered.values()]


def run_all(ticker, tick, history):
    """Run every registered plugin against this tick. Never raises - a
    broken plugin just scores 0 and gets logged."""
    _discover()
    scores = {}
    for name, plugin in _registered.items():
        try:
            s = float(plugin.score(ticker, tick, history))
            scores[name] = max(0.0, min(100.0, s))
        except Exception as e:
            print(f"[plugins] {name} raised an error, scoring 0: {e}")
            scores[name] = 0.0
    _last_scores[ticker] = scores
    return scores


def average_score(scores: dict) -> float:
    if not scores:
        return 0.0
    return sum(scores.values()) / len(scores)


def get_last_scores(ticker=None):
    _discover()
    if ticker:
        return _last_scores.get(ticker, {})
    return dict(_last_scores)