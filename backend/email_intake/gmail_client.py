"""Gmail API client with OAuth, message fetching, and label management."""

from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from . import config
from .models import EmailMessage

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
TOKEN_FILE = config.GMAIL_TOKEN_FILE
CREDENTIALS_FILE = config.GMAIL_CREDENTIALS_FILE
SEARCH_QUERY = (
    f"-label:{config.PROCESSED_LABEL} in:inbox is:unread "
    f"{config.GMAIL_SEARCH_FILTER}"
).strip()


class GmailClient:
    """Thin wrapper around the Gmail API for the intake pipeline."""

    def __init__(self) -> None:
        self._service = build("gmail", "v1", credentials=self._authenticate())
        self._label_id: Optional[str] = None

    # ------------------------------------------------------------------ auth
    def _authenticate(self) -> Credentials:
        creds: Optional[Credentials] = None
        if os.path.exists(TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDENTIALS_FILE, SCOPES
                )
                creds = flow.run_local_server(port=0)
            with open(TOKEN_FILE, "w", encoding="utf-8") as token:
                token.write(creds.to_json())

        return creds

    # ----------------------------------------------------------------- fetch
    def fetch_unprocessed(self) -> list[EmailMessage]:
        """Return unprocessed inbox messages as :class:`EmailMessage` objects."""
        response = (
            self._service.users()
            .messages()
            .list(
                userId="me",
                q=SEARCH_QUERY,
                maxResults=config.MAX_EMAILS_PER_CYCLE,
            )
            .execute()
        )

        messages = response.get("messages", [])
        results: list[EmailMessage] = []
        for ref in messages:
            full = (
                self._service.users()
                .messages()
                .get(userId="me", id=ref["id"], format="full")
                .execute()
            )
            results.append(self._parse_message(full))
        return results

    # --------------------------------------------------------------- parsing
    def _parse_message(self, message: dict) -> EmailMessage:
        payload = message.get("payload", {})
        headers = {
            h["name"].lower(): h["value"] for h in payload.get("headers", [])
        }

        sender = parseaddr(headers.get("from", ""))[1] or headers.get("from", "")
        subject = headers.get("subject", "")
        body = self._extract_body(payload)

        # Gmail internalDate is epoch milliseconds.
        internal = message.get("internalDate")
        if internal is not None:
            received_at = datetime.fromtimestamp(
                int(internal) / 1000, tz=timezone.utc
            )
        else:
            received_at = datetime.now(tz=timezone.utc)

        return EmailMessage(
            id=message["id"],
            thread_id=message.get("threadId", ""),
            sender=sender,
            subject=subject,
            body=body,
            received_at=received_at,
        )

    def _extract_body(self, payload: dict) -> str:
        """Recursively extract the first text/plain body, base64url-decoded."""
        mime_type = payload.get("mimeType", "")
        body = payload.get("body", {})

        if mime_type == "text/plain" and body.get("data"):
            return self._decode(body["data"])

        for part in payload.get("parts", []):
            text = self._extract_body(part)
            if text:
                return text

        # Fallback: any body data present on this node.
        if body.get("data"):
            return self._decode(body["data"])
        return ""

    @staticmethod
    def _decode(data: str) -> str:
        decoded = base64.urlsafe_b64decode(data.encode("utf-8"))
        return decoded.decode("utf-8", errors="replace")

    # ---------------------------------------------------------------- labels
    def _get_or_create_label_id(self) -> str:
        if self._label_id is not None:
            return self._label_id

        existing = (
            self._service.users().labels().list(userId="me").execute()
        )
        for label in existing.get("labels", []):
            if label["name"] == config.PROCESSED_LABEL:
                self._label_id = label["id"]
                return self._label_id

        created = (
            self._service.users()
            .labels()
            .create(
                userId="me",
                body={
                    "name": config.PROCESSED_LABEL,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            )
            .execute()
        )
        self._label_id = created["id"]
        return self._label_id

    def mark_processed(self, message_id: str) -> None:
        """Apply the processed label to the given message."""
        label_id = self._get_or_create_label_id()
        self._service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id]},
        ).execute()

    def mark_read(self, message_id: str) -> None:
        """Mark the given message as read by removing the UNREAD label."""
        self._service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()
