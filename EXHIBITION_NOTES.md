# What's new — exhibition cheat sheet

## 0. Setup (do this first, before evaluators arrive)
In `backend/.env`, add:
```
AUTHORIZED_EMAIL=<the compliance officer's email you want alerts sent to>
ALERT_EMAIL_MIN_RISK=HIGH        # or CRITICAL if you only want the most severe
```
`GMAIL_USER` / `GMAIL_APP_PASSWORD` should already be set from before. Restart the backend after editing `.env`.

Everything below runs on the SQLite/in-memory fallbacks your project already has — if Docker/Postgres/Neo4j aren't running, it still works, just with a local file DB and an in-memory graph. No new pip/npm installs are required.

---

## 1. Autonomous alert email (the one you promised)
**Where:** `backend/app/notifications.py`, hooked into `risk_scorer.score_tick()`.
**What to say:** "The moment the ensemble raises a HIGH or CRITICAL alert, the system automatically emails the authorized compliance person — no analyst has to click anything. It's fire-and-forget on a background thread so it never blocks the live feed."
**How to demo:** inject a scenario (pump_and_dump / insider_trading), wait for a CRITICAL alert, show the recipient's inbox.

## 2. VWAP Deviation Detector
**Where:** `backend/app/ml/vwap_detector.py`
**What to say:** "A separate, deterministic rule-based check — industry standard — flags when price deviates sharply from the volume-weighted average price of recent ticks. Independent of the ML ensemble."

## 3. Volume Spike Z-Score Detector
**Where:** `backend/app/ml/volume_zscore.py`
**What to say:** "A second statistical detector — no training needed — flags abnormal volume spikes using a rolling z-score. Complements the isolation forest."

## 4. Coordinated Multi-Stock Meta-Alert
**Where:** `/api/coordinated-alerts`, purple banner at the top of the dashboard.
**What to say:** "A meta-detection layer above individual alerts — if 2+ unrelated stocks go CRITICAL within a 2-minute window, that's statistically unlikely to be coincidence, so we flag it as a distinct, higher-severity, market-wide event."
**How to demo:** inject scenarios on 2 different tickers within 2 minutes of each other.

## 5. Wash Trading tab
**Where:** already-existing backend graph-cycle detection (`neo4j_client.detect_wash_trading`), now wired into the frontend.
**What to say:** "Finds trader pairs who trade heavily with each other and almost no one else — a classic wash-trading fingerprint, computed via graph pattern matching."

## 6. Trader Reputation History / Trend
**Where:** `trader_reputation_history` table, click any trader row in the Reputation tab.
**What to say:** "Every time a trader is flagged we snapshot their reputation score, so we can show how it escalated over time, not just the current number."

## 7. Configurable Detection Settings panel
**Where:** ⚙️ Settings tab — sliders for every model weight and every risk-level cutoff.
**What to say:** "The ensemble isn't a black box — an admin can retune how much each detector contributes, or where LOW/MEDIUM/HIGH/CRITICAL cutoffs sit, live, without redeploying."

## 8. Audit Log
**Where:** 🧾 Audit Log tab, backed by the `audit_log` table.
**What to say:** "Every analyst review decision, manual escalation, and autonomous email is logged with who/what/when — this is what a real compliance system needs for accountability."

## 9. Manual Escalate button
**Where:** "🚨 Escalate to Authority" button in the alert detail modal.
**What to say:** "Beyond the automatic email, an analyst can manually force an immediate re-notification for a specific alert — useful when they want a second opinion escalated right away."

## 10. Export regulatory report as a printable PDF
**Where:** "🖨️ Export PDF" button in the alert detail modal — opens a formatted report in a new tab and triggers the browser print dialog (Save as PDF).
**What to say:** "The system already generates a text regulatory report; this makes it a polished, presentable document an analyst can actually hand to compliance or save as a PDF."

---

## Quick precision/recall/F1 talking point (already existed, worth repeating)
`/api/evaluation` computes precision/recall/F1 by comparing injected scenario ground-truth ticks against raised alerts, per ticker — mention this if asked "how do you know it works."
