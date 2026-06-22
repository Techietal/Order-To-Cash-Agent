"""Data models for the email intake pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Category(str, Enum):
    """Classification categories for incoming email."""

    ORDER = "ORDER"
    PAYMENT = "PAYMENT"
    DISPUTE = "DISPUTE"
    OTHER = "OTHER"
    NEEDS_REVIEW = "NEEDS_REVIEW"


@dataclass
class EmailMessage:
    """A normalized representation of a Gmail message."""

    id: str
    thread_id: str
    sender: str
    subject: str
    body: str
    received_at: datetime


@dataclass
class Classification:
    """The result of classifying an :class:`EmailMessage`."""

    category: Category
    confidence: float
    reason: str
