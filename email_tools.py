"""
email_tools.py — ARJUN Gmail Integration
Send emails, attach files, check inbox via IMAP/SMTP.
Imported by tools.py and registered as Qwen tool functions.
"""

import smtplib
import imaplib
import email
import os
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.header import decode_header

from config import (
    GMAIL_ADDRESS, GMAIL_APP_PASSWORD,
    GMAIL_IMAP_SERVER, GMAIL_SMTP_SERVER, GMAIL_SMTP_PORT
)

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str, attachment_path: str = "") -> str:
    """
    Send an email from Arjun's Gmail account.
    Optionally attach a file (e.g. a generated Python script).
    """
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        return "Gmail credentials are not configured in the .env file."

    try:
        msg = MIMEMultipart()
        msg["From"]    = GMAIL_ADDRESS
        msg["To"]      = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            filename = os.path.basename(attachment_path)
            part.add_header("Content-Disposition", f"attachment; filename={filename}")
            msg.attach(part)

        with smtplib.SMTP(GMAIL_SMTP_SERVER, GMAIL_SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, to, msg.as_string())

        attach_note = f" with attachment {os.path.basename(attachment_path)}" if attachment_path else ""
        return f"Email sent to {to}{attach_note}."

    except Exception as e:
        logger.error(f"send_email error: {e}")
        return f"Failed to send email: {str(e)}"


def check_email(max_messages: int = 5) -> str:
    """
    Check the most recent unread emails in Arjun's Gmail inbox.
    Returns a plain-text summary of each message.
    """
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        return "Gmail credentials are not configured in the .env file."

    try:
        mail = imaplib.IMAP4_SSL(GMAIL_IMAP_SERVER)
        mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        mail.select("inbox")

        status, messages = mail.search(None, "UNSEEN")
        if status != "OK" or not messages[0]:
            mail.logout()
            return "No unread emails in the inbox right now."

        email_ids = messages[0].split()
        # Most recent first
        email_ids = email_ids[-max_messages:][::-1]

        summaries = []
        for eid in email_ids:
            status, msg_data = mail.fetch(eid, "(RFC822)")
            if status != "OK":
                continue

            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            # Decode subject
            subject_raw = msg.get("Subject", "No Subject")
            subject_parts = decode_header(subject_raw)
            subject = ""
            for part, enc in subject_parts:
                if isinstance(part, bytes):
                    subject += part.decode(enc or "utf-8", errors="replace")
                else:
                    subject += part

            sender = msg.get("From", "Unknown Sender")
            date   = msg.get("Date", "Unknown Date")

            # Get plain text body
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = payload.decode("utf-8", errors="replace")[:300]
                            break
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="replace")[:300]

            summaries.append(
                f"From {sender} on {date}. Subject: {subject}. Message: {body.strip()}"
            )

        mail.logout()

        if not summaries:
            return "Could not read any emails."

        return " Next email: ".join(summaries)

    except Exception as e:
        logger.error(f"check_email error: {e}")
        return f"Failed to check email: {str(e)}"


# ── Email Tool Schemas for Ollama ──
EMAIL_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": (
                "Send an email from Arjun's Gmail account to any address. "
                "Use this when the user asks to email someone, send research results, "
                "share a generated script, or deliver any work via email."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "The recipient email address."
                    },
                    "subject": {
                        "type": "string",
                        "description": "The email subject line."
                    },
                    "body": {
                        "type": "string",
                        "description": "The plain text body of the email."
                    },
                    "attachment_path": {
                        "type": "string",
                        "description": "Optional full file path to attach to the email."
                    }
                },
                "required": ["to", "subject", "body"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_email",
            "description": (
                "Check Arjun's Gmail inbox for unread emails and return a summary "
                "of recent messages. Use when the user asks to check email or read messages."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "max_messages": {
                        "type": "integer",
                        "description": "How many recent unread emails to fetch. Default is 5."
                    }
                },
                "required": []
            }
        }
    }
]
