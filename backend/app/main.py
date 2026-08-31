import asyncio
import json
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.db.postgres import get_connection, init_schema
from app.db import neo4j_client
from app.ingestion.feed import market_feed
from app.ml.risk_scorer import score_tick
from app.ml.lstm_autoencoder import train_and_save
from app.core.config import TICKER_DISPLAY
from app.notifications import notify_authorized_person, is_configured as email_is_configured
from fastapi import UploadFile, File
import pandas as pd
import io
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from pydantic import BaseModel
from typing import Optional, Dict
import smtplib
from email.mime.text import MIMEText
import os
from dotenv import load_dotenv
load_dotenv()

# ---- Email config (Gmail App Password) ----
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

SCENARIO_EXPLANATIONS = {
    "insider_trading": {
        "why": "A small cluster of trader IDs began accumulating large buy positions right before a sharp price increase, consistent with trading on non-public information.",
        "immediate_issue": "Coordinated buying ahead of a price move suggests information asymmetry — some traders may know something the market doesn't yet.",
        "recommended_action": "Freeze the flagged trader accounts pending review, cross-check for connections to insiders/employees, and report to compliance/SEBI if confirmed.",
    },
    "pump_and_dump": {
        "why": "Price was artificially inflated through concentrated buying, then rapidly sold off once it peaked — a classic pump-and-dump pattern.",
        "immediate_issue": "Retail investors who bought during the artificial spike are now holding losses after the dump.",
        "recommended_action": "Flag and suspend the involved trader accounts, issue a market alert to other participants, and review historical activity for repeat behavior.",
    },
    "spoofing": {
        "why": "Abnormally large orders were placed to create a false impression of demand, without genuine intent to execute at that size.",
        "immediate_issue": "Other market participants may be misled into trading based on fake order book depth.",
        "recommended_action": "Cancel/investigate the suspicious orders, apply a trading restriction on the account, and monitor order-to-trade ratio going forward.",
    },
    "layering": {
        "why": "Multiple layered buy/sell orders were placed across price levels to manipulate perceived market depth and steer price direction.",
        "immediate_issue": "Genuine buyers/sellers are reacting to a distorted, manipulated order book rather than real supply/demand.",
        "recommended_action": "Void the layered orders where possible, escalate to market surveillance team, and consider a temporary trading halt on the security.",
    },
}

app = FastAPI(title="Market Manipulation Detection & Insider Trading Prevention System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

connected_clients: list[WebSocket] = []


async def broadcast(message: dict):
    dead = []
    for ws in connected_clients:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for d in dead:
        connected_clients.remove(d)


async def polling_loop():
    conn = get_connection()
    poll_count = 0
    while True:
        try:
            conn2 = get_connection()
            cur = conn2.cursor()
            cur.execute("SELECT cmd_id, ticker, scenario, length_ticks FROM scenario_commands WHERE processed=FALSE ORDER BY created_at LIMIT 1")
            cmd = cur.fetchone()
            if cmd:
                cmd_id, ticker, scenario, length_ticks = cmd
                market_feed.inject_scenario(ticker, scenario, length_ticks)
                cur.execute("UPDATE scenario_commands SET processed=TRUE WHERE cmd_id=%s", (cmd_id,))
                await broadcast({"type": "scenario_injected", "ticker": ticker, "scenario": scenario})

            ticks = market_feed.poll(conn2)
            for tick in ticks:
                history = market_feed.tick_history[tick["ticker"]]
                result = score_tick(conn2, tick, history)
                await broadcast({"type": "tick", "tick": {**tick, "timestamp": tick["timestamp"].isoformat()}, "score": {**result, "timestamp": result["timestamp"].isoformat()}})
                if result["alert_type"]:
                    await broadcast({"type": "alert", "alert": {**result, "timestamp": result["timestamp"].isoformat()}})

            poll_count += 1
            if poll_count % 20 == 0:
                for ticker, history in market_feed.tick_history.items():
                    normal_ticks = [t for t in history if not t["meta"].get("scenario")]
                    train_and_save(ticker, normal_ticks)

            conn2.close()
        except Exception as e:
            print(f"polling error: {e}")
        await asyncio.sleep(2)


@app.on_event("startup")
async def startup():
    init_schema()
    neo4j_client.init_constraints()
    asyncio.create_task(polling_loop())


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/ticks")
def get_ticks(limit: int = 500):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT ticker, tick_timestamp, close, volume, scenario FROM price_ticks ORDER BY tick_timestamp DESC LIMIT %s", (limit,))
    rows = cur.fetchall()
    def fmt_ts(ts):
        return ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
    return [{"ticker": r[0], "timestamp": fmt_ts(r[1]), "close": r[2], "volume": r[3], "scenario": r[4]} for r in rows]


@app.get("/api/scenario-explanation/{alert_id}")
def scenario_explanation(alert_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT ticker, alert_type, risk_level, composite_score FROM alerts WHERE alert_id=%s", (alert_id,))
    row = cur.fetchone()
    if not row:
        return {"error": "not found"}
    ticker, atype, risk, comp = row
    key = atype.lower().replace(" ", "_") if atype else None
    explanation = SCENARIO_EXPLANATIONS.get(key, {
        "why": "Anomalous trading pattern detected by the model ensemble.",
        "immediate_issue": "Pattern doesn't match typical market behavior for this security.",
        "recommended_action": "Flag for manual analyst review.",
    })
    return {"ticker": ticker, "alert_type": atype, "risk_level": risk, "composite_score": comp, **explanation}


@app.post("/api/analyze-csv")
async def analyze_csv(file: UploadFile = File(...)):
    contents = await file.read()
    df = pd.read_csv(io.BytesIO(contents))

    required_cols = {"ticker", "timestamp", "close", "volume"}
    missing = required_cols - set(df.columns)
    if missing:
        return {"error": f"CSV is missing required columns: {', '.join(missing)}"}

    conn = get_connection()
    flagged_rows = []
    history_by_ticker = {}

    for _, row in df.iterrows():
        ticker = row["ticker"]
        tick = {
            "ticker": ticker,
            "timestamp": pd.to_datetime(row["timestamp"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
            "meta": {},
        }
        history = history_by_ticker.setdefault(ticker, [])

        try:
            result = score_tick(conn, tick, history)
        except Exception:
            history.append(tick)
            continue

        history.append(tick)

        if result.get("alert_type"):
            flagged_rows.append({
                "ticker": ticker,
                "timestamp": str(row["timestamp"]),
                "close": tick["close"],
                "alert_type": result["alert_type"],
                "composite_score": result.get("composite_score"),
                "risk_level": result.get("risk_level"),
            })

    return {
        "total_rows": len(df),
        "flagged_count": len(flagged_rows),
        "flagged_rows": flagged_rows,
        "summary": f"{len(flagged_rows)} suspicious trades flagged out of {len(df)} rows.",
    }


@app.get("/api/alerts")
def get_alerts(limit: int = 50):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""SELECT alert_id, ticker, alert_type, risk_level, composite_score, temporal_score,
                   sentiment_score, network_score, lstm_score, vwap_score, volume_z_score,
                   alert_timestamp, status
                   FROM alerts ORDER BY alert_timestamp DESC LIMIT %s""", (limit,))
    rows = cur.fetchall()
    cols = ["alert_id","ticker","alert_type","risk_level","composite_score","temporal_score",
            "sentiment_score","network_score","lstm_score","vwap_score","volume_z_score",
            "alert_timestamp","status"]
    def fmt(v):
        return v.isoformat() if hasattr(v, "isoformat") else v
    return [dict(zip(cols, [fmt(v) for v in r])) for r in rows]


@app.post("/api/alerts/{alert_id}/review")
def review_alert(alert_id: int, decision: str, actor: str = "analyst"):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE alerts SET status=%s WHERE alert_id=%s", (decision, alert_id))
    from app.db.postgres import log_audit
    log_audit(conn, alert_id, f"review_{decision}", actor, f"Analyst marked alert #{alert_id} as {decision}")
    return {"status": "updated"}


@app.post("/api/escalate/{alert_id}")
def escalate_alert(alert_id: int, actor: str = "analyst"):
    """Manual escalation — immediately (re-)sends the autonomous email for this
    alert regardless of whether it already fired, and logs who triggered it."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT ticker, alert_type, risk_level, composite_score FROM alerts WHERE alert_id=%s", (alert_id,))
    row = cur.fetchone()
    if not row:
        return {"error": "not found"}
    ticker, atype, risk, comp = row
    if not email_is_configured():
        return {"status": "not_configured", "message": "Set GMAIL_USER / GMAIL_APP_PASSWORD / AUTHORIZED_EMAIL in backend/.env"}
    notify_authorized_person(alert_id, ticker, atype, risk, comp, conn=conn, force=True)
    from app.db.postgres import log_audit
    log_audit(conn, alert_id, "manual_escalation", actor, f"{actor} manually escalated alert #{alert_id} to authorized person")
    return {"status": "escalated"}


@app.get("/api/audit-log")
def get_audit_log(limit: int = 100):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""SELECT audit_id, alert_id, action, actor, details, action_timestamp
                   FROM audit_log ORDER BY action_timestamp DESC LIMIT %s""", (limit,))
    rows = cur.fetchall()
    def fmt(v):
        return v.isoformat() if hasattr(v, "isoformat") else v
    cols = ["audit_id", "alert_id", "action", "actor", "details", "action_timestamp"]
    return [dict(zip(cols, [fmt(v) for v in r])) for r in rows]


@app.get("/api/coordinated-alerts")
def coordinated_alerts():
    """Cross-ticker meta-detection: if 2+ distinct securities go CRITICAL within
    a short window, that's statistically unlikely to be coincidence — flag it
    as a distinct, higher-severity, market-wide coordinated event."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""SELECT ticker, alert_type, alert_timestamp FROM alerts
                   WHERE risk_level='CRITICAL' ORDER BY alert_timestamp DESC LIMIT 20""")
    rows = cur.fetchall()
    if len(rows) < 2:
        return {"coordinated": False, "tickers": []}
    def parse(ts):
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts)
            except ValueError:
                return datetime.now()
        return ts
    recent = [r for r in rows if (datetime.now() - parse(r[2])).total_seconds() < 120]
    distinct_tickers = sorted(set(r[0] for r in recent))
    return {
        "coordinated": len(distinct_tickers) >= 2,
        "tickers": distinct_tickers,
        "window_seconds": 120,
    }


@app.get("/api/trader-reputation-history/{trader_id}")
def trader_reputation_history(trader_id: str, limit: int = 30):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""SELECT reputation_score, flag_count, recorded_at FROM trader_reputation_history
                   WHERE trader_id=%s ORDER BY recorded_at ASC LIMIT %s""", (trader_id, limit))
    rows = cur.fetchall()
    def fmt(v):
        return v.isoformat() if hasattr(v, "isoformat") else v
    return [{"reputation_score": r[0], "flag_count": r[1], "recorded_at": fmt(r[2])} for r in rows]


@app.get("/api/settings/weights")
def get_weights():
    from app.ml.risk_scorer import WEIGHTS, RISK_THRESHOLDS
    return {"weights": WEIGHTS, "risk_thresholds": RISK_THRESHOLDS, "email_configured": email_is_configured()}


class WeightsUpdate(BaseModel):
    weights: Optional[Dict[str, float]] = None
    risk_thresholds: Optional[Dict[str, float]] = None


@app.get("/api/plugins")
def get_plugins():
    """Junior-extension point: lists every Detector plugin auto-discovered
    from ml/plugins/, plus each plugin's most recent score per ticker."""
    from app.ml import plugins as detector_plugins
    return {
        "loaded": detector_plugins.list_plugins(),
        "latest_scores": detector_plugins.get_last_scores(),
    }
def update_weights(req: WeightsUpdate):
    from app.ml import risk_scorer
    if req.weights:
        for k, v in req.weights.items():
            if k in risk_scorer.WEIGHTS:
                risk_scorer.WEIGHTS[k] = float(v)
    if req.risk_thresholds:
        for k, v in req.risk_thresholds.items():
            if k in risk_scorer.RISK_THRESHOLDS:
                risk_scorer.RISK_THRESHOLDS[k] = float(v)
    return {"status": "updated", "weights": risk_scorer.WEIGHTS, "risk_thresholds": risk_scorer.RISK_THRESHOLDS}


@app.post("/api/inject")
def inject_scenario(ticker: str, scenario: str, length_ticks: int = 5):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO scenario_commands (ticker, scenario, length_ticks) VALUES (%s,%s,%s)", (ticker, scenario, length_ticks))
    return {"status": "queued"}

@app.post("/api/debug/train-classifier")
def train_classifier_endpoint():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT temporal_score, sentiment_score, network_score, lstm_score, alert_type FROM alerts")
    rows = cur.fetchall()
    if len(rows) < 10:
        return {"error": f"need at least 10 alerts to train, currently have {len(rows)}"}
    training_rows = [{"temporal": r[0], "sentiment": r[1], "network": r[2], "lstm": r[3], "label": r[4]} for r in rows]
    from app.ml.supervised_classifier import train_classifier
    clf, metrics = train_classifier(training_rows)
    return {"status": "trained" if clf else "failed", "metrics": metrics}
@app.post("/api/debug/retrain-from-confirmed")
def retrain_from_confirmed():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT temporal_score, sentiment_score, network_score, lstm_score, alert_type FROM alerts WHERE status='confirmed'")
    confirmed = cur.fetchall()
    cur.execute("SELECT temporal_score, sentiment_score, network_score, lstm_score, alert_type FROM alerts WHERE status='dismissed'")
    dismissed = cur.fetchall()
    rows = [{"temporal": r[0], "sentiment": r[1], "network": r[2], "lstm": r[3], "label": r[4]} for r in confirmed]
    rows += [{"temporal": r[0], "sentiment": r[1], "network": r[2], "lstm": r[3], "label": "Normal"} for r in dismissed]
    if len(rows) < 6:
        return {"error": f"need more confirmed/dismissed alerts first (have {len(rows)}, need 6+). Go confirm/dismiss some alerts in the UI."}
    from app.ml.supervised_classifier import train_classifier
    clf, metrics = train_classifier(rows)
    return {"status": "retrained from analyst feedback", "metrics": metrics, "training_examples": len(rows)}
@app.get("/api/predict-label")
def predict_label_endpoint(temporal: float, sentiment: float, network: float, lstm: float):
    from app.ml.supervised_classifier import predict_label
    pred = predict_label(temporal, sentiment, network, lstm)
    return {"predicted_label": pred, "classifier_trained": pred is not None}
@app.post("/api/debug/fast-forward")
async def fast_forward(count: int = 25):
    conn = get_connection()
    for _ in range(count):
        ticks = market_feed.poll(conn)
        for tick in ticks:
            history = market_feed.tick_history[tick["ticker"]]
            score_tick(conn, tick, history)
    return {"status": "done", "ticks_generated": count}

@app.get("/api/alert-news/{alert_id}")
def get_alert_news(alert_id: int):
    from app.ml.risk_scorer import get_alert_headlines
    headlines = get_alert_headlines(alert_id)
    return {"headlines": headlines}
@app.get("/api/news-feed")
def news_feed():
    from app.ingestion.news import fetch_real_headlines
    result = {}
    for ticker in TICKER_DISPLAY.values():
        headlines = fetch_real_headlines(ticker)
        result[ticker] = headlines or []
    return result
@app.get("/api/trader-network")
def get_trader_network():
    return neo4j_client.get_all_trader_edges()


@app.get("/api/wash-trading")
def get_wash_trading():
    return neo4j_client.detect_wash_trading()


@app.get("/api/heatmap")
def get_heatmap():
    conn = get_connection()
    cur = conn.cursor()
    results = []
    for ticker in TICKER_DISPLAY.values():
        cur.execute("""SELECT risk_level, composite_score FROM alerts
                       WHERE ticker=%s ORDER BY alert_timestamp DESC LIMIT 1""", (ticker,))
        row = cur.fetchone()
        if row:
            results.append({"ticker": ticker, "risk": row[0], "score": row[1]})
        else:
            results.append({"ticker": ticker, "risk": "LOW", "score": 5.0})
    return results


@app.get("/api/trader-reputation")
def get_trader_reputation_list():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT trader_id, flag_count, reputation_score FROM trader_reputation ORDER BY reputation_score DESC LIMIT 20")
    rows = cur.fetchall()
    return [{"trader_id": r[0], "flag_count": r[1], "reputation_score": r[2]} for r in rows]


@app.get("/api/regulatory-report/{alert_id}")
def generate_regulatory_report(alert_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""SELECT alert_id, ticker, alert_type, risk_level, composite_score,
                   temporal_score, sentiment_score, network_score, lstm_score,
                   vwap_score, volume_z_score,
                   alert_timestamp, status FROM alerts WHERE alert_id=%s""", (alert_id,))
    row = cur.fetchone()
    if not row:
        return {"error": "not found"}
    aid, ticker, atype, risk, comp, temp, sent, net, lstm, vwap, volz, ts, status = row
    report = f"""SUSPICIOUS ACTIVITY REPORT
{'='*50}
Generated: {datetime.now().isoformat()}
Alert ID: {aid}  |  Security: {ticker}
Type: {atype}  |  Risk: {risk}  |  Composite Score: {comp}/100
Detected: {ts}

DETECTION BREAKDOWN
  Temporal (Isolation Forest): {temp}
  Sentiment (FinBERT): {sent}
  Network (GNN): {net}
  Temporal (LSTM Autoencoder): {lstm}
  VWAP Deviation (rule-based): {vwap}
  Volume Z-Score (rule-based): {volz}

STATUS: {str(status).upper()}
RECOMMENDATION: {"Immediate escalation to compliance" if risk == "CRITICAL" else "Flagged for analyst review"}
"""
    return {"report": report}


@app.post("/api/debug/train-models")
async def force_train_models():
    from app.ml.lstm_autoencoder import train_and_save
    trained_lstm = []
    for ticker, history in market_feed.tick_history.items():
        normal_ticks = [t for t in history if not t["meta"].get("scenario")]
        if train_and_save(ticker, normal_ticks):
            trained_lstm.append(ticker)

    edges = neo4j_client.get_all_trader_edges()
    from app.ml import gnn as gnn_module
    model, data, id_to_idx = gnn_module.load_or_train_gnn(edges)
    gnn_trained = model is not None

    return {"lstm_trained_for": trained_lstm, "gnn_trained": gnn_trained, "edge_count": len(edges)}


@app.get("/api/explain/{alert_id}")
def explain_alert(alert_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""SELECT ticker, alert_type, risk_level, composite_score,
                   temporal_score, sentiment_score, network_score, lstm_score,
                   vwap_score, volume_z_score
                   FROM alerts WHERE alert_id=%s""", (alert_id,))
    row = cur.fetchone()
    if not row:
        return {"error": "not found"}
    ticker, atype, risk, comp, temp, sent, net, lstm, vwap, volz = row
    from app.ml.risk_scorer import WEIGHTS
    contributions = {
        "temporal_isolation_forest": round(WEIGHTS["temporal"] * temp, 2),
        "sentiment_finbert": round(WEIGHTS["sentiment"] * sent, 2),
        "network_gnn": round(WEIGHTS["network"] * net, 2),
        "temporal_lstm": round(WEIGHTS["lstm"] * lstm, 2),
        "vwap_deviation": round(WEIGHTS.get("vwap", 0) * (vwap or 0), 2),
        "volume_zscore": round(WEIGHTS.get("volume_z", 0) * (volz or 0), 2),
    }
    total = sum(contributions.values()) or 1
    breakdown = [{"model": k, "contribution": v, "percent": round(v/total*100, 1)} for k, v in contributions.items()]
    breakdown.sort(key=lambda x: -x["contribution"])
    return {"ticker": ticker, "alert_type": atype, "risk_level": risk, "composite_score": comp, "breakdown": breakdown}


@app.get("/api/market-summary")
def market_summary():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM alerts")
    total_alerts = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM alerts WHERE status='open'")
    open_alerts = cur.fetchone()[0]
    cur.execute("SELECT alert_type, COUNT(*) FROM alerts GROUP BY alert_type")
    by_type = cur.fetchall()
    cur.execute("SELECT risk_level, COUNT(*) FROM alerts GROUP BY risk_level")
    by_risk = cur.fetchall()
    cur.execute("SELECT COUNT(*) FROM price_ticks")
    total_ticks = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT trader_id) FROM trades")
    total_traders = cur.fetchone()[0]
    return {
        "total_alerts": total_alerts, "open_alerts": open_alerts, "total_ticks": total_ticks,
        "total_traders": total_traders,
        "alerts_by_type": {r[0]: r[1] for r in by_type},
        "alerts_by_risk": {r[0]: r[1] for r in by_risk},
    }


@app.get("/api/evaluation")
def evaluation_metrics():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM price_ticks WHERE scenario IS NOT NULL")
    true_positive_candidates = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM price_ticks WHERE scenario IS NULL")
    true_negative_candidates = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM alerts")
    total_alerts_raised = cur.fetchone()[0]

    # Per-ticker comparison: for each ticker, how many manipulated ticks occurred
    # vs how many alerts were raised. Treat each alert as attempting to catch one
    # manipulated tick — excess alerts beyond manipulated ticks count as false
    # positives, uncaught manipulated ticks count as false negatives. This is a
    # finer-grained (and more honest) approximation than a ticker-level yes/no check.
    cur.execute("SELECT ticker, COUNT(*) FROM price_ticks WHERE scenario IS NOT NULL GROUP BY ticker")
    manipulated_by_ticker = dict(cur.fetchall())

    cur.execute("SELECT ticker, COUNT(*) FROM alerts GROUP BY ticker")
    alerts_by_ticker = dict(cur.fetchall())

    all_tickers = set(manipulated_by_ticker) | set(alerts_by_ticker)
    tp = fp = fn = 0
    for ticker in all_tickers:
        m = manipulated_by_ticker.get(ticker, 0)
        a = alerts_by_ticker.get(ticker, 0)
        tp += min(m, a)
        fp += max(0, a - m)
        fn += max(0, m - a)

    precision_est = round(tp / max(1, tp + fp), 3)
    recall_est = round(tp / max(1, tp + fn), 3)
    f1 = round(2 * precision_est * recall_est / max(0.001, precision_est + recall_est), 3)

    return {
        "manipulated_ticks_injected": true_positive_candidates,
        "normal_ticks": true_negative_candidates,
        "total_alerts_raised": total_alerts_raised,
        "estimated_precision": precision_est,
        "estimated_recall": recall_est,
        "estimated_f1": f1,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "note": "Precision/recall computed per-ticker by comparing count of manipulated ticks vs alerts raised — ground truth derived from injected scenario labels via controlled simulation."
    }

@app.get("/api/export/alerts-csv")
def export_alerts_csv():
    import csv
    import io as _io
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""SELECT alert_id, ticker, alert_type, risk_level, composite_score,
                   temporal_score, sentiment_score, network_score, lstm_score,
                   alert_timestamp, status FROM alerts ORDER BY alert_timestamp DESC""")
    rows = cur.fetchall()
    output = _io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Alert ID","Ticker","Type","Risk","Composite","Temporal","Sentiment","Network","LSTM","Timestamp","Status"])
    writer.writerows(rows)
    return {"csv": output.getvalue()}


# ---- Email sending (Gmail SMTP) ----
class EmailRequest(BaseModel):
    recipient: str
    subject: str
    body: str


@app.post("/api/send-email")
def send_email(req: EmailRequest):
    try:
        msg = MIMEText(req.body)
        msg["Subject"] = req.subject
        msg["From"] = GMAIL_USER
        msg["To"] = req.recipient

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, [req.recipient], msg.as_string())

        return {"status": "sent"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}