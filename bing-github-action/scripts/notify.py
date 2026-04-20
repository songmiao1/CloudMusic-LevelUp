#!/usr/bin/env python3

import os
import smtplib
from email.mime.text import MIMEText


def _as_bool(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def send(title: str, content: str):
    server = os.environ.get("SMTP_SERVER", "").strip()
    sender = os.environ.get("SMTP_EMAIL", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    recipients = [item.strip() for item in os.environ.get("SMTP_TO", "").split(",") if item.strip()]

    if not (server and sender and password and recipients):
        print("\n--- [通知] ---")
        print(f"标题: {title}")
        print(f"内容:\n{content}")
        print("-------------------------------")
        return

    sender_name = os.environ.get("SMTP_NAME", sender).strip()
    smtp_ssl = _as_bool(os.environ.get("SMTP_SSL", "true"))
    port = int(os.environ.get("SMTP_PORT", "465" if smtp_ssl else "25"))

    message = MIMEText(content, "plain", "utf-8")
    message["Subject"] = title
    message["From"] = f"{sender_name} <{sender}>"
    message["To"] = ", ".join(recipients)

    if smtp_ssl:
        client = smtplib.SMTP_SSL(server, port, timeout=30)
    else:
        client = smtplib.SMTP(server, port, timeout=30)

    try:
        client.login(sender, password)
        client.sendmail(sender, recipients, message.as_string())
    finally:
        client.quit()
