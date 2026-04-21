#!/usr/bin/env python3

import os
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr


def _as_bool(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_server_and_port() -> tuple[str, int | None]:
    server = os.environ.get("SMTP_SERVER", "").strip()
    port_raw = os.environ.get("SMTP_PORT", "").strip()

    host = server
    port = None

    if server.startswith("[") and "]:" in server and not port_raw:
        host, parsed_port = server.rsplit("]:", 1)
        host = f"{host}]"
        if parsed_port.isdigit():
            port = int(parsed_port)
    elif server.count(":") == 1 and not port_raw:
        maybe_host, maybe_port = server.rsplit(":", 1)
        if maybe_port.isdigit():
            host = maybe_host
            port = int(maybe_port)

    if port_raw.isdigit():
        port = int(port_raw)

    return host, port


def send(title: str, content: str) -> bool:
    server, port = _resolve_server_and_port()
    sender = os.environ.get("SMTP_EMAIL", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    recipient_raw = os.environ.get("SMTP_TO", "").strip() or sender
    recipients = [item.strip() for item in recipient_raw.split(",") if item.strip()]

    if not (server and sender and password and recipients):
        print("\n--- [通知] ---")
        print(f"标题: {title}")
        print(f"内容:\n{content}")
        print("-------------------------------")
        return True

    sender_name = os.environ.get("SMTP_NAME", sender).strip()
    smtp_ssl = _as_bool(os.environ.get("SMTP_SSL", "true"))

    message = MIMEText(content, "plain", "utf-8")
    message["Subject"] = Header(title, "utf-8")
    message["From"] = formataddr((str(Header(sender_name, "utf-8")), sender))
    message["To"] = ", ".join(recipients)

    if smtp_ssl:
        client = smtplib.SMTP_SSL(server, port, timeout=30) if port else smtplib.SMTP_SSL(server, timeout=30)
    else:
        client = smtplib.SMTP(server, port, timeout=30) if port else smtplib.SMTP(server, timeout=30)

    try:
        client.login(sender, password)
        client.sendmail(sender, recipients, message.as_string())
        return True
    finally:
        client.quit()
