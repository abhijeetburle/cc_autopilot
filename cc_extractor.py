"""
cc_extractor.py
---------------
Extracts raw transaction rows from any credit card statement PDF.
Uses pdfplumber for text extraction + Claude API for intelligent parsing.
Card-agnostic: behaviour driven by config YAML.
"""

import re
import json
import logging
from pathlib import Path
from typing import Optional

import pdfplumber

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  PDF TEXT EXTRACTION
# ─────────────────────────────────────────────

def extract_pdf_text(pdf_path: str) -> str:
    """Extract all text from a PDF, page by page."""
    pages = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text(x_tolerance=3, y_tolerance=3)
                if text:
                    pages.append(text)
    except Exception as e:
        logger.error(f"pdfplumber failed on {pdf_path}: {e}")
        raise
    return "\n\n--- PAGE BREAK ---\n\n".join(pages)


# ─────────────────────────────────────────────
#  CARD CONFIG DETECTION
# ─────────────────────────────────────────────

def detect_card_config(pdf_text: str, configs: dict) -> Optional[dict]:
    """
    Given extracted PDF text and a dict of loaded configs,
    return the matching config or None.
    """
    text_upper = pdf_text.upper()
    for config_id, config in configs.items():
        fingerprints = config.get("pdf_fingerprints", [])
        if any(fp.upper() in text_upper for fp in fingerprints):
            logger.info(f"Matched card config: {config_id}")
            return config
    logger.warning("No card config matched — will attempt generic extraction")
    return None


# ─────────────────────────────────────────────
#  STATEMENT HEADER METADATA
# ─────────────────────────────────────────────

def extract_statement_metadata(pdf_text: str, config: dict) -> dict:
    """Extract statement date, card number, cardholder from PDF text."""
    meta = {
        "statement_date": None,
        "card_number": None,
        "cardholder_primary": config.get("cardholders", {}).get("primary", ""),
        "bank": config.get("card", {}).get("bank", "Unknown"),
        "card_name": config.get("card", {}).get("name", "Unknown"),
    }

    # Statement date — look for patterns like "Statement Date:11/10/2022"
    date_patterns = [
        r"Statement\s+Date[:\s]+(\d{2}/\d{2}/\d{4})",
        r"Statement\s+Date[:\s]+(\d{2}-\d{2}-\d{4})",
        r"Statement\s+Date[:\s]+(\d{2}\s+\w+\s+\d{4})",
        r"Billing\s+Date[:\s]+(\d{2}/\d{2}/\d{4})",
        r"Date\s+of\s+Statement[:\s]+(\d{2}/\d{2}/\d{4})",
    ]
    for pat in date_patterns:
        m = re.search(pat, pdf_text, re.IGNORECASE)
        if m:
            meta["statement_date"] = m.group(1)
            break

    # Card number — masked format
    card_patterns = [
        r"Card\s+No[:\s]+(\d{4}\s*\d{2}XX\s*XXXX\s*\d{4})",
        r"Card\s+No[:\s]+([\dX\s]{16,19})",
        r"Account\s+Number[:\s]+([\dX\s]{16,19})",
    ]
    for pat in card_patterns:
        m = re.search(pat, pdf_text, re.IGNORECASE)
        if m:
            meta["card_number"] = m.group(1).strip()
            break

    return meta


# ─────────────────────────────────────────────
#  CLAUDE-POWERED TRANSACTION EXTRACTION
# ─────────────────────────────────────────────

def extract_transactions_via_claude(
    pdf_text: str,
    config: dict,
    claude_client,
    source_pdf: str
) -> list[dict]:
    """
    Send PDF text to Claude with card-specific instructions.
    Returns a list of transaction dicts.
    """
    card_name  = config.get("card", {}).get("name", "credit card")
    currency   = config.get("parsing", {}).get("currency", "Rs.")
    date_fmt   = config.get("parsing", {}).get("date_format", "%d/%m/%Y")
    credit_ind = config.get("parsing", {}).get("credit_indicator", "Cr")
    cardholders = config.get("cardholders", {})
    ch_list = [v for v in cardholders.values() if v]

    prompt = f"""You are a precise financial data extractor.
Extract ALL transactions from this {card_name} statement PDF text.

RULES:
1. Return ONLY a JSON array — no markdown, no explanation, no preamble.
2. Each transaction must have these exact keys:
   - "date"          : string in DD/MM/YYYY format
   - "cardholder"    : name as shown in statement (e.g. {', '.join(ch_list)})
   - "description"   : full raw transaction description as printed
   - "reward_points" : integer (0 if not shown or N/A)
   - "amount"        : float, always POSITIVE
   - "is_credit"     : boolean — true if this is a payment/refund/credit
3. A transaction IS a credit if the amount has "{credit_ind}" suffix, or words like
   "credit", "payment", "refund", "cashback", "waiver" in description.
4. Include ALL rows: purchases, payments, credits, fees, GST charges, EMI entries,
   cashback credits, surcharge waivers — everything.
5. DO NOT skip any transaction. DO NOT summarise.
6. If reward points column is absent (e.g. card has no points), use 0.
7. Cardholder: use the section header name shown above each group of transactions.
   Known cardholders: {', '.join(ch_list)}

PDF TEXT:
{pdf_text[:15000]}

Return JSON array only:"""

    response = claude_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()

    # Strip markdown code fences if present
    raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
    raw = raw.strip()

    try:
        transactions = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}\nRaw response: {raw[:500]}")
        # Attempt to salvage partial JSON
        try:
            # Find the array
            m = re.search(r'\[.*\]', raw, re.DOTALL)
            if m:
                transactions = json.loads(m.group(0))
            else:
                raise ValueError("No JSON array found in response")
        except Exception:
            logger.error("Could not salvage JSON — returning empty list")
            return []

    # Normalise and validate each row
    normalised = []
    for txn in transactions:
        if not isinstance(txn, dict):
            continue
        norm = {
            "date":          str(txn.get("date", "")).strip(),
            "cardholder":    str(txn.get("cardholder", "")).strip(),
            "description":   str(txn.get("description", "")).strip(),
            "reward_points": int(txn.get("reward_points", 0) or 0),
            "amount":        abs(float(txn.get("amount", 0) or 0)),
            "is_credit":     bool(txn.get("is_credit", False)),
            "source_pdf":    Path(source_pdf).name,
        }
        if norm["date"] and norm["description"] and norm["amount"] > 0:
            normalised.append(norm)

    logger.info(f"Extracted {len(normalised)} transactions from {Path(source_pdf).name}")
    return normalised


# ─────────────────────────────────────────────
#  LARGE PDF HANDLING (multi-chunk)
# ─────────────────────────────────────────────

def extract_transactions_chunked(
    pdf_text: str,
    config: dict,
    claude_client,
    source_pdf: str,
    chunk_size: int = 12000
) -> list[dict]:
    """
    For large PDFs, split by page breaks and process in chunks.
    Deduplicates across chunks by (date, description, amount).
    """
    if len(pdf_text) <= chunk_size:
        return extract_transactions_via_claude(pdf_text, config, claude_client, source_pdf)

    logger.info(f"Large PDF ({len(pdf_text)} chars) — processing in chunks")
    pages = pdf_text.split("--- PAGE BREAK ---")

    # Group pages into chunks under chunk_size
    chunks, current, current_len = [], [], 0
    for page in pages:
        if current_len + len(page) > chunk_size and current:
            chunks.append("\n".join(current))
            current, current_len = [], 0
        current.append(page)
        current_len += len(page)
    if current:
        chunks.append("\n".join(current))

    all_txns = []
    seen = set()
    for i, chunk in enumerate(chunks):
        logger.info(f"Processing chunk {i+1}/{len(chunks)}")
        txns = extract_transactions_via_claude(chunk, config, claude_client, source_pdf)
        for t in txns:
            key = (t["date"], t["description"][:30], t["amount"])
            if key not in seen:
                seen.add(key)
                all_txns.append(t)

    logger.info(f"Total after dedup across chunks: {len(all_txns)}")
    return all_txns
