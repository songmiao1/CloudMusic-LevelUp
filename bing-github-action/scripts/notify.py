#!/usr/bin/env python3

import os
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr


def _as_bool(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def send(title: str, content: str) -> bool:
    server = os.environ.get("SMTP_SERVER", "").strip()
    sender = os.environ.get("SMTP_EMAIL", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    recipients = [item.strip() for item in os.environ.get("SMTP_TO", "").split(",") if item.strip()]

    if not (server and sender and password and recipients):
        print("\n--- [通知] ---")
        print(f"标题: {title}")
        print(f"内容:\n{content}")
        print("-------------------------------")
        return True

    sender_name = os.environ.get("SMTP_NAME", sender).strip()
    smtp_ssl = _as_bool(os.environ.get("SMTP_SSL", "true"))
    port_raw = os.environ.get("SMTP_PORT", "").strip()

    message = MIMEText(content, "plain", "utf-8")
    message["Subject"] = Header(title, "utf-8")
    message["From"] = formataddr((str(Header(sender_name, "utf-8")), sender))
    message["To"] = ", ".join(recipients)

    if smtp_ssl:
        client = smtplib.SMTP_SSL(server, int(port_raw), timeout=30) if port_raw else smtplib.SMTP_SSL(server, timeout=30)
    else:
        client = smtplib.SMTP(server, int(port_raw), timeout=30) if port_raw else smtplib.SMTP(server, timeout=30)

    try:
        client.login(sender, password)
        client.sendmail(sender, recipients, message.as_string())
        return True
    finally:
        client.quit()
