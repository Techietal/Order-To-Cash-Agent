"""
Structured PDF invoice generator (reportlab).

Produces a professional, GST-compliant tax invoice as raw PDF bytes so it can be
attached to outbound customer emails. No file is written to disk — the caller
receives an in-memory ``bytes`` payload ready for MIME attachment.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Optional, Sequence, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)

# Company / seller identity shown in the invoice header.
SELLER_NAME = "MAQ Manufacturing"
SELLER_ADDRESS = "Plot 14, Industrial Estate, Hyderabad, Telangana 500032, India"
SELLER_GSTIN = "36AABCM1234A1Z5"
SELLER_EMAIL = "finance@maqmanufacturing.com"

_BRAND = colors.HexColor("#1f3a5f")
_LIGHT = colors.HexColor("#eef2f7")


def _money(value: float) -> str:
    """Format a number as Indian-Rupee currency."""
    return f"Rs. {float(value or 0):,.2f}"


def build_invoice_pdf(
    *,
    invoice_id: str,
    order_id: str,
    customer_name: str,
    customer_email: str = "",
    customer_gstin: str = "",
    billing_address: str = "",
    line_items: Sequence[dict],
    subtotal_inr: float,
    gst_pct: float,
    gst_amount_inr: float,
    total_inr: float,
    invoice_date: Optional[datetime] = None,
    due_date: Optional[datetime] = None,
    payment_terms_days: int = 30,
    notes: str = "",
) -> bytes:
    """Render a structured tax invoice and return the PDF as bytes.

    ``line_items`` is a sequence of dicts with keys:
    ``description``, ``quantity``, ``unit_price_inr``, ``amount_inr``.
    """
    invoice_date = invoice_date or datetime.utcnow()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Invoice {invoice_id}",
        author=SELLER_NAME,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "InvTitle", parent=styles["Title"], textColor=_BRAND, fontSize=22, spaceAfter=2
    )
    seller_style = ParagraphStyle(
        "Seller", parent=styles["Normal"], fontSize=9, leading=12, textColor=colors.HexColor("#444444")
    )
    label_style = ParagraphStyle(
        "Label", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#888888")
    )
    value_style = ParagraphStyle("Value", parent=styles["Normal"], fontSize=10, leading=13)
    right_value = ParagraphStyle("RightValue", parent=value_style, alignment=TA_RIGHT)
    footer_style = ParagraphStyle(
        "Footer", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#888888"), alignment=TA_CENTER
    )

    elements = []

    # ── Header: seller identity + TAX INVOICE badge ─────────────────────────
    header = Table(
        [[
            Paragraph(
                f"<b>{SELLER_NAME}</b><br/>{SELLER_ADDRESS}<br/>"
                f"GSTIN: {SELLER_GSTIN}<br/>{SELLER_EMAIL}",
                seller_style,
            ),
            Paragraph("TAX INVOICE", title_style),
        ]],
        colWidths=[105 * mm, 69 * mm],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    elements.append(header)
    elements.append(Spacer(1, 8 * mm))

    # ── Meta strip: invoice/order numbers and dates ─────────────────────────
    due = due_date or invoice_date
    meta = Table(
        [
            [
                Paragraph("INVOICE NO.", label_style),
                Paragraph("ORDER NO.", label_style),
                Paragraph("INVOICE DATE", label_style),
                Paragraph("DUE DATE", label_style),
            ],
            [
                Paragraph(f"<b>{invoice_id}</b>", value_style),
                Paragraph(order_id, value_style),
                Paragraph(invoice_date.strftime("%d %b %Y"), value_style),
                Paragraph(due.strftime("%d %b %Y"), value_style),
            ],
        ],
        colWidths=[43.5 * mm] * 4,
    )
    meta.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(meta)
    elements.append(Spacer(1, 8 * mm))

    # ── Bill-to block ───────────────────────────────────────────────────────
    bill_to_lines = [f"<b>{customer_name}</b>"]
    if billing_address:
        bill_to_lines.append(billing_address)
    if customer_gstin:
        bill_to_lines.append(f"GSTIN: {customer_gstin}")
    if customer_email:
        bill_to_lines.append(customer_email)
    elements.append(Paragraph("BILL TO", label_style))
    elements.append(Paragraph("<br/>".join(bill_to_lines), value_style))
    elements.append(Spacer(1, 6 * mm))

    # ── Line items table ────────────────────────────────────────────────────
    table_data = [["#", "Description", "Qty", "Unit Price", "Amount"]]
    for idx, item in enumerate(line_items, start=1):
        table_data.append([
            str(idx),
            item.get("description", ""),
            f"{item.get('quantity', 0):g}",
            _money(item.get("unit_price_inr", 0)),
            _money(item.get("amount_inr", 0)),
        ])

    items_table = Table(table_data, colWidths=[10 * mm, 84 * mm, 18 * mm, 31 * mm, 31 * mm])
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT]),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 4 * mm))

    # ── Totals block (right-aligned) ────────────────────────────────────────
    totals = Table(
        [
            ["Subtotal", _money(subtotal_inr)],
            [f"GST ({gst_pct:g}%)", _money(gst_amount_inr)],
            ["Total Due", _money(total_inr)],
        ],
        colWidths=[31 * mm, 31 * mm],
        hAlign="RIGHT",
    )
    totals.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEABOVE", (0, 2), (-1, 2), 0.6, _BRAND),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 2), (-1, 2), _BRAND),
        ("FONTSIZE", (0, 2), (-1, 2), 11),
    ]))
    elements.append(totals)
    elements.append(Spacer(1, 10 * mm))

    # ── Payment terms / notes ───────────────────────────────────────────────
    terms = (
        f"Payment due within {payment_terms_days} days of the invoice date. "
        "Please quote the invoice number with your remittance."
    )
    if notes:
        terms = f"{notes}<br/>{terms}"
    elements.append(Paragraph("PAYMENT TERMS", label_style))
    elements.append(Paragraph(terms, value_style))
    elements.append(Spacer(1, 14 * mm))

    elements.append(Paragraph(
        f"This is a computer-generated invoice issued by {SELLER_NAME}.",
        footer_style,
    ))

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def build_invoice_pdf_attachment(**kwargs) -> Tuple[str, bytes, str]:
    """Convenience wrapper returning a ``(filename, bytes, mime_subtype)`` tuple."""
    invoice_id = kwargs.get("invoice_id", "invoice")
    pdf_bytes = build_invoice_pdf(**kwargs)
    return f"{invoice_id}.pdf", pdf_bytes, "pdf"
