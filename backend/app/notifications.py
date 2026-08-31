"""
Autonomous notification layer.

When the detection pipeline raises an alert at or above ALERT_EMAIL_MIN_RISK,
this module automatically emails the authorized/compliance person configured
in .env — no analyst has to click a button. Sending happens on a background
thread so it never blocks the 2-second polling loop.
"""
import os
import smtplib
import threading
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
AUTHORIZED_EMAIL = os.getenv("AUTHORIZED_EMAIL", "")
ALERT_EMAIL_MIN_RISK = os.getenv("ALERT_EMAIL_MIN_RISK", "HIGH")  # HIGH or CRITICAL

RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

# in-memory dedupe so the same alert_id never gets emailed twice
_already_notified = set()


def _send_smtp(subject, body, recipient):
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = GMAIL_USER
        msg["To"] = recipient
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, [recipient], msg.as_string())
        print(f"[AUTO-ALERT-EMAIL] sent to {recipient}: {subject}")
    except Exception as e:
        print(f"[AUTO-ALERT-EMAIL] failed to send: {e}")


def is_configured():
    return bool(GMAIL_USER and GMAIL_APP_PASSWORD and AUTHORIZED_EMAIL)


def notify_authorized_person(alert_id, ticker, alert_type, risk_level, composite_score, conn=None, force=False):
    """
    Fire-and-forget autonomous notification. Called by the risk scorer right
    after an alert is inserted. Returns True if a send was triggered.
    """
    if not is_configured():
        print("[AUTO-ALERT-EMAIL] skipped — set GMAIL_USER / GMAIL_APP_PASSWORD / AUTHORIZED_EMAIL in backend/.env")
        return False

    if not force:
        if RISK_ORDER.get(risk_level, 0) < RISK_ORDER.get(ALERT_EMAIL_MIN_RISK, 2):
            return False
        if alert_id in _already_notified:
            return False

    subject = f"[MARKET SURVEILLANCE ALERT] {risk_level} — {ticker} — {alert_type}"
    body = (
        "AUTOMATED MARKET MANIPULATION DETECTION ALERT\n"
        "This notification was generated and sent automatically by the system — no analyst action was required.\n\n"
        f"Alert ID:        #{alert_id}\n"
        f"Security:        {ticker}\n"
        f"Alert Type:      {alert_type}\n"
        f"Risk Level:      {risk_level}\n"
        f"Composite Score: {composite_score}/100\n\n"
        "Please log in to the compliance dashboard to review supporting evidence and take action.\n"
    )
    threading.Thread(target=_send_smtp, args=(subject, body, AUTHORIZED_EMAIL), daemon=True).start()
    _already_notified.add(alert_id)

    if conn is not None:
        from app.db.postgres import log_audit
        log_audit(conn, alert_id, "auto_email_sent", "system",
                   f"Autonomous notification sent to {AUTHORIZED_EMAIL} (risk={risk_level})")
    return True
