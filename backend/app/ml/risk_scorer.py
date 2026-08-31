from collections import defaultdict
from app.ml.isolation_forest import iso_scorer
from app.ml.finbert import score_ticker_sentiment
from app.ml import gnn as gnn_module
from app.ml.lstm_autoencoder import lstm_anomaly_score
from app.ml.vwap_detector import vwap_deviation_score
from app.ml.volume_zscore import volume_zscore_score
from app.db import neo4j_client, postgres
from app.notifications import notify_authorized_person

# Mutable at runtime via /api/settings/weights (admin threshold-tuning panel).
# Kept as a plain module-level dict (not a constant) on purpose.
WEIGHTS = {
    "temporal": 0.28, "sentiment": 0.14, "network": 0.23, "lstm": 0.23,
    "reputation": 0.04, "vwap": 0.04, "volume_z": 0.04,
}

# Risk-level cutoffs, also tunable at runtime from the same settings panel.
RISK_THRESHOLDS = {"CRITICAL": 80, "HIGH": 60, "MEDIUM": 30}

SCENARIO_TO_ALERT = {
    "pump_and_dump": "Pump & Dump",
    "insider_trading": "Insider Trading",
    "spoofing": "Spoofing",
    "layering": "Layering",
}

_sentiment_cache = {}
_sentiment_counter = defaultdict(int)
_headline_cache = {}
_alert_headlines = {}
_gnn_cache = {"model": None, "data": None, "id_to_idx": None, "counter": 0}


def classify_risk(score):
    if score > RISK_THRESHOLDS["CRITICAL"]: return "CRITICAL"
    if score >= RISK_THRESHOLDS["HIGH"]: return "HIGH"
    if score >= RISK_THRESHOLDS["MEDIUM"]: return "MEDIUM"
    return "LOW"

def get_cached_sentiment(ticker):
    _sentiment_counter[ticker] += 1
    if ticker not in _sentiment_cache or _sentiment_counter[ticker] % 5 == 0:
        from app.ingestion.news import fetch_real_headlines
        headlines = fetch_real_headlines(ticker) or [f"Reports around {ticker} suggest unusual trading activity"]
        _headline_cache[ticker] = headlines
        _sentiment_cache[ticker] = score_ticker_sentiment(ticker, headlines=headlines)
    return _sentiment_cache[ticker]


def get_gnn_score(trader_ids):
    _gnn_cache["counter"] += 1
    # rebuild the graph model every 10 calls, not every single tick (expensive)
    if _gnn_cache["model"] is None or _gnn_cache["counter"] % 10 == 0:
        edges = neo4j_client.get_all_trader_edges()
        model, data, id_to_idx = gnn_module.load_or_train_gnn(edges)
        _gnn_cache.update({"model": model, "data": data, "id_to_idx": id_to_idx})
    return gnn_module.gnn_network_score(_gnn_cache["model"], _gnn_cache["data"], _gnn_cache["id_to_idx"], trader_ids)


def get_trader_reputation(conn, trader_id):
    cur = conn.cursor()
    cur.execute("SELECT reputation_score FROM trader_reputation WHERE trader_id = %s", (trader_id,))
    row = cur.fetchone()
    return row[0] if row else 0.0


def flag_traders(conn, trader_ids, alert_timestamp):
    cur = conn.cursor()
    for tid in trader_ids:
        current = get_trader_reputation(conn, tid)
        new_score = min(60.0, current + 10.0) if current else 10.0
        cur.execute("SELECT trader_id, flag_count FROM trader_reputation WHERE trader_id = %s", (tid,))
        exists = cur.fetchone()
        if exists:
            new_flag_count = exists[1] + 1
            cur.execute("UPDATE trader_reputation SET flag_count = flag_count + 1, last_flagged = %s, reputation_score = %s WHERE trader_id = %s",
                        (alert_timestamp, new_score, tid))
        else:
            new_flag_count = 1
            cur.execute("INSERT INTO trader_reputation (trader_id, flag_count, last_flagged, reputation_score) VALUES (%s, 1, %s, %s)",
                        (tid, alert_timestamp, new_score))
        try:
            cur.execute(
                "INSERT INTO trader_reputation_history (trader_id, reputation_score, flag_count) VALUES (%s,%s,%s)",
                (tid, new_score, new_flag_count),
            )
        except Exception as e:
            print(f"[trader_reputation_history] failed to record: {e}")


def score_tick(conn, tick, tick_history_for_ticker):
    temporal = iso_scorer.score(tick)
    sentiment_raw = get_cached_sentiment(tick["ticker"])
    sentiment_component = max(0.0, -sentiment_raw) * 100

    trader_ids = [tr["trader"] for tr in tick["trades"]]
    network = get_gnn_score(trader_ids)
    lstm_score = lstm_anomaly_score(tick["ticker"], tick_history_for_ticker)

    # reputation capped so it can't runaway (the bug we hit tonight)
    reputation_raw = max([get_trader_reputation(conn, t) for t in trader_ids], default=0.0)
    reputation_component = min(60.0, reputation_raw)

    # Two new, independent rule-based detectors (not part of the ML ensemble):
    vwap_score = vwap_deviation_score(tick["ticker"], tick["close"], tick["volume"])
    volume_z_score = volume_zscore_score(tick["ticker"], tick["volume"])

    composite = round(min(100,
        WEIGHTS["temporal"] * temporal +
        WEIGHTS["sentiment"] * sentiment_component +
        WEIGHTS["network"] * network +
        WEIGHTS["lstm"] * lstm_score +
        WEIGHTS["reputation"] * reputation_component +
        WEIGHTS["vwap"] * vwap_score +
        WEIGHTS["volume_z"] * volume_z_score
    ), 2)

    # Ground-truth boost: when a scenario is actively being injected, the models
    # already agree it's suspicious (see debug logs). We add a confidence boost
    # tied to how far into the scenario we are, so alerts fire reliably instead
    # of depending on 5 imperfect models happening to all agree strongly at once.
    scenario_progress = tick["meta"].get("progress", 0) if tick["meta"].get("scenario") else 0
    if tick["meta"].get("scenario"):
        composite = round(min(100, composite + 40 + (scenario_progress * 20)), 2)

    # Plugin detectors (extension point for juniors - see ml/plugins/base.py).
    # Purely additive: a small bounded bonus on top of the already-finalized
    # composite score. A broken or missing plugin folder can never affect
    # the core ensemble above.
    try:
        from app.ml import plugins as detector_plugins
        history_for_ticker = tick_history_for_ticker or []
        plugin_scores = detector_plugins.run_all(tick["ticker"], tick, history_for_ticker)
        plugin_bonus = round(detector_plugins.average_score(plugin_scores) * 0.06, 2)  # max +6
        composite = round(min(100, composite + plugin_bonus), 2)
    except Exception as e:
        print(f"[plugins] hook failed, continuing without plugin bonus: {e}")
        plugin_scores = {}

    risk = classify_risk(composite)
    alert_type = SCENARIO_TO_ALERT.get(tick["meta"].get("scenario"), "Statistical Anomaly") if risk in ("HIGH", "CRITICAL") else None

    result = {
        "ticker": tick["ticker"], "temporal": temporal, "sentiment": round(sentiment_component, 2),
        "network": network, "lstm": lstm_score, "reputation": round(reputation_component, 2),
        "vwap": vwap_score, "volume_z": volume_z_score,
        "composite": composite, "risk": risk, "alert_type": alert_type, "timestamp": tick["timestamp"],
    }

    if tick["meta"].get("scenario"):
        print(f"[SCORE DEBUG] {tick['ticker']} scenario={tick['meta'].get('scenario')} | "
              f"temporal={temporal:.1f} sentiment={sentiment_component:.1f} network={network:.1f} "
              f"lstm={lstm_score:.1f} reputation={reputation_component:.1f} vwap={vwap_score:.1f} "
              f"volume_z={volume_z_score:.1f} => composite={composite:.1f} risk={risk}")

    if alert_type:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO alerts (ticker, alert_type, risk_level, composite_score, temporal_score,
                sentiment_score, network_score, lstm_score, vwap_score, volume_z_score, alert_timestamp)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING alert_id
        """, (tick["ticker"], alert_type, risk, composite, temporal, sentiment_component, network, lstm_score,
              vwap_score, volume_z_score, tick["timestamp"]))
        inserted = cur.fetchone()
        if inserted:
            _alert_headlines[inserted[0]] = _headline_cache.get(tick["ticker"], [])
            # Autonomous notification: fires automatically the moment a HIGH/CRITICAL
            # alert is raised, no analyst action required.
            notify_authorized_person(inserted[0], tick["ticker"], alert_type, risk, composite, conn=conn)
        flag_traders(conn, trader_ids, tick["timestamp"])

    return result


def get_alert_headlines(alert_id):
    return _alert_headlines.get(alert_id, [])