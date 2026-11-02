"""Notification rules and provider adapters (FR-017 to FR-021, SRS 4.2).

The rule is a pure function shared by the server and the simulator. Providers
sit behind one send() method, so the delivery channel can change without
touching queue logic.
"""
import json
import os
import smtplib
import urllib.request
from email.message import EmailMessage


def alert_purposes(minutes_to_eta, eta_shift, arrival_sent, alert_minutes, change_minutes):
    """Which alerts a waiting patient should get now (decision tree DT-5, decision table 4).

    minutes_to_eta: ETA minus now, in minutes (None when no ETA is available).
    eta_shift: how far the ETA moved since the patient was last told, in minutes (None if never told).
    """
    if minutes_to_eta is None:
        return []
    if minutes_to_eta <= alert_minutes and not arrival_sent:
        return ["arrival"]
    if eta_shift is not None and eta_shift >= change_minutes:
        return ["eta_change"]
    return []


class LogProvider:
    """Default provider: writes the alert to the server log. There is no delivery
    receipt, so the outcome is 'unconfirmed', never 'delivered' (NFR-007)."""
    name = "log"

    def send(self, to, subject, body):
        print(f"[alert] to={to} | {subject} | {body}", flush=True)
        return "unconfirmed"


class SmtpProvider:
    """Email through any SMTP server. Configure OPD_SMTP_HOST, OPD_SMTP_PORT,
    OPD_SMTP_USER, OPD_SMTP_PASSWORD and OPD_SMTP_FROM."""
    name = "email"

    def __init__(self):
        self.host = os.environ["OPD_SMTP_HOST"]
        self.port = int(os.environ.get("OPD_SMTP_PORT", "587"))
        self.user = os.environ.get("OPD_SMTP_USER")
        self.password = os.environ.get("OPD_SMTP_PASSWORD")
        self.sender = os.environ.get("OPD_SMTP_FROM", self.user or "opd@localhost")

    def send(self, to, subject, body):
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.sender, to, subject
        msg.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=15) as s:
            s.starttls()
            if self.user:
                s.login(self.user, self.password)
            s.send_message(msg)
        return "sent"  # accepted by the mail server; inbox delivery is not confirmed


class WebhookProvider:
    """SMS or messaging through an HTTP gateway. POSTs {"to", "subject", "body"} as
    JSON to OPD_SMS_WEBHOOK. A reply of {"status": "delivered"} is recorded as delivered."""
    name = "sms"

    def __init__(self):
        self.url = os.environ["OPD_SMS_WEBHOOK"]
        self.token = os.environ.get("OPD_SMS_TOKEN")

    def send(self, to, subject, body):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.url, json.dumps({"to": to, "subject": subject, "body": body}).encode(), headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            reply = json.loads(r.read() or b"{}")
        return "delivered" if reply.get("status") == "delivered" else "sent"


class MockProvider:
    """Simulation-only provider. Never contacts anyone; the caller decides failure (SIM-004)."""
    name = "mock"

    def send(self, to, subject, body, fail=False):
        if fail:
            raise ConnectionError("simulated provider failure")
        return "delivered"


def provider_for(channel):
    """Pick the configured provider for a patient's channel, falling back to the log."""
    if channel == "email" and os.environ.get("OPD_SMTP_HOST"):
        return SmtpProvider()
    if channel == "sms" and os.environ.get("OPD_SMS_WEBHOOK"):
        return WebhookProvider()
    return LogProvider()
