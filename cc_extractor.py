"""
cc_extractor.py
---------------
Extracts raw transaction rows from any credit card statement PDF.
Uses pdfplumber for text extraction and config-driven parsing.
Card-agnostic: behaviour driven by config YAML.
"""

import re
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import pdfplumber

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  PDF TEXT EXTRACTION
# ─────────────────────────────────────────────

def extract_pdf_text(pdf_path: str, passwords: list = None) -> str:
    """Extract all text from a PDF, page by page.
    Tries passwords if PDF is password-protected.
    Raises PasswordError if all passwords fail.
    Raises PermissionError if file is locked/not accessible.
    """
    import errno
    if passwords is None:
        passwords = []
    
    pages = []
    last_error = None
    
    # Try without password first
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text(x_tolerance=3, y_tolerance=3)
                if text:
                    pages.append(text)
        return "\n\n--- PAGE BREAK ---\n\n".join(pages)
    except Exception as e:
        last_error = e
        
        # Check if it's a file lock / permission issue (not password)
        error_msg = str(e).lower()
        if any(keyword in error_msg for keyword in ["permission denied", "file is in use", "locked", "io error"]):
            logger.error(f"Cannot access {pdf_path}: {e}")
            raise PermissionError(f"PDF file is locked or not accessible: {e}")
        
        # Check for actual password error
        if not any(keyword in error_msg for keyword in ["password", "encrypted", "security", "pdfpasswordincorrect", "passwordincorrect"]):
            # Not a password error and not a lock — might be corrupted, not a PDF, etc.
            if passwords:
                # Still worth trying passwords in case error message is ambiguous
                pass
            else:
                # No passwords to try, so fail immediately
                logger.error(f"Failed to extract {pdf_path}: {e}")
                raise ValueError(f"Failed to extract PDF: {e}")
    
    # If password-protected, try each password
    if passwords:
        for pwd in passwords:
            try:
                with pdfplumber.open(pdf_path, password=pwd) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text(x_tolerance=3, y_tolerance=3)
                        if text:
                            pages.append(text)
                logger.info(f"Successfully opened {pdf_path} with provided password")
                return "\n\n--- PAGE BREAK ---\n\n".join(pages)
            except Exception as e:
                last_error = e
                continue
    
    # All attempts failed
    error_msg = f"Failed to extract {pdf_path}: {last_error}"
    logger.error(error_msg)
    raise PasswordError(error_msg) if passwords else ValueError(error_msg)


class PasswordError(Exception):
    """Raised when PDF requires password and all attempts fail."""
    pass


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
        r"Statement\s+Date[:\s]+(\d{1,2}\s+\w+,?\s+\d{4})",
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
#  LOCAL TRANSACTION EXTRACTION
# ─────────────────────────────────────────────

def normalize_whitespace(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.strip())


def parse_amount(amount_str: str) -> float:
    cleaned = amount_str.replace(",", "").replace("(", "-").replace(")", "")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_date_string(date_str: str, date_format: str = "%d/%m/%Y") -> str:
    formats = [
        date_format,
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d-%b-%Y",
        "%Y-%m-%d",
        "%d %b %Y",
        "%d %b, %Y",
        "%d %B %Y",
        "%d %B, %Y",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            continue
    return date_str.strip()


def build_date_regex(config: dict) -> str:
    custom = config.get("parsing", {}).get("date_regex")
    if custom:
        return custom

    date_format = config.get("parsing", {}).get("date_format", "%d/%m/%Y")
    if "%d/%m/%Y" in date_format:
        return r"\d{1,2}/\d{1,2}/\d{4}"
    if "%d-%m-%Y" in date_format:
        return r"\d{1,2}-\d{1,2}-\d{4}"
    if "%d-%b-%Y" in date_format or "%d-%B-%Y" in date_format:
        return r"\d{1,2}-[A-Za-z]{3,9}-\d{4}"
    return r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"


def find_transaction_section(pdf_text: str, config: dict) -> str:
    headers = config.get("parsing", {}).get("transaction_section_headers", []) or []
    end_markers = config.get("parsing", {}).get("transaction_section_end_markers", []) or []
    text_upper = pdf_text.upper()

    start = None
    for header in headers:
        idx = text_upper.find(header.upper())
        if idx != -1 and (start is None or idx < start):
            start = idx
    if start is None:
        return pdf_text

    section = pdf_text[start:]
    section_upper = section.upper()
    end_index = None
    for marker in end_markers:
        idx = section_upper.find(marker.upper())
        if idx != -1 and (end_index is None or idx < end_index):
            end_index = idx
    if end_index is not None:
        section = section[:end_index]
    return section


def is_noise_line(line: str, config: dict) -> bool:
    if not line:
        return True

    noise_patterns = [
        r'^Page\s+\d+\s+of\s+\d+',
        r'^---\s*PAGE\s*BREAK\s*---$',
        r'^DATE\s*&\s*TIME',
        r'^TRANSACTION\s+DESCRIPTION',
        r'^REWARDS',
        r'^AMOUNT',
        r'^INTL\.#',
        r'^POINTS',
        r'^TRANSACTION\s+DETAILS',
        r'^DOMESTIC\s+TRANSACTIONS',
        r'^INTERNATIONAL\s+TRANSACTIONS',
        r'^STATEMENT\s+PERIOD',
        r'^EARNINGS',
        r'^PREVIOUS\s+BALANCE',
        r'^IMPORTANT\s+MESSAGES',
        r'^FOR\s+EXCLUSIVE\s+OFFERS',
        r'^INFINIA\s+CREDIT\s+CARD\s+STATEMENT',
        r'^HDFC\s+Bank\s+Credit\s+Cards',
        r'^ICICI\s+Bank\s+Credit\s+Card',
        r'^CREDIT\s+CARD\s+STATEMENT',
        r'^DOWNLOAD\s+THE\s+iMOBILE\s+PAY',
        r'^OFFERS\s+ON\s+YOUR\s+CARD',
        r'^HSN\s+CODE',
        r'^STATEMENT\s+PERIOD',
    ]
    if any(re.match(pat, line, re.IGNORECASE) for pat in noise_patterns):
        return True
    if 'cid:' in line.lower():
        return True
    if re.search(r'\d{4}X{8}\d{4}', line):
        return True
    return False


def split_transaction_rows(section_text: str, config: dict) -> list[str]:
    date_regex = build_date_regex(config)
    rows = []
    current = None

    for line in section_text.splitlines():
        line = normalize_whitespace(line)
        if not line or is_noise_line(line, config):
            continue

        if re.search(rf"\b{date_regex}\b", line):
            if current:
                rows.append(current)
            current = line
        elif current:
            current += " " + line

    if current:
        rows.append(current)
    return rows


def parse_transaction_row(row_text: str, config: dict) -> Optional[dict]:
    date_regex = build_date_regex(config)
    amount_regex = config.get("parsing", {}).get("amount_regex", r"\d+(?:,\d{3})*(?:\.\d{1,2})?")
    credit_indicator = config.get("parsing", {}).get("credit_indicator", "Cr")
    expected_columns = [c.lower() for c in config.get("parsing", {}).get("expected_columns", []) or []]
    has_points_column = any("point" in col or "cashback" in col for col in expected_columns)

    date_match = re.search(rf"\b{date_regex}\b", row_text)
    if not date_match:
        return None

    date_str = parse_date_string(date_match.group(0), config.get("parsing", {}).get("date_format", "%d/%m/%Y"))
    remainder = row_text[date_match.end():].strip()
    # Use a broader amount regex that handles Indian lakh format (e.g. 1,00,000.00)
    broad_amount_regex = amount_regex.replace(r"(?:,\d{3})*", r"(?:,\d{2,3})*")
    amount_match = re.search(rf"({broad_amount_regex})\s*(?:{re.escape(credit_indicator)})?\s*[^0-9]*$", row_text, re.IGNORECASE)

    reward_points = 0
    amount = 0.0
    if amount_match:
        amount = parse_amount(amount_match.group(1))
        if has_points_column:
            prev_text = row_text[:amount_match.start()].strip()
            prev_amounts = re.findall(broad_amount_regex, prev_text)
            if prev_amounts:
                reward_points = int(round(parse_amount(prev_amounts[-1])))

    is_credit = bool(re.search(rf"\b{re.escape(credit_indicator)}\b", row_text, re.IGNORECASE))
    is_credit = is_credit or bool(re.search(r"\b(CREDIT|REFUND|PAYMENT|CASHBACK|WAIVER|REVERSAL)\b", row_text, re.IGNORECASE))

    desc = remainder
    if amount_match:
        desc = desc[:desc.rfind(amount_match.group(1))].strip() if amount_match.group(1) in desc else desc
    desc = re.sub(rf"\b{re.escape(credit_indicator)}\b", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\b(CR|DR)\b", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\b\d{9,}\b", "", desc)
    # Clean HDFC specific patterns: remove time stamps like "| 16:25" and reward points like "+ 25 C"
    # Extract timestamp before removing it (used to distinguish same-day same-amount transactions)
    time_match = re.search(r'\|\s*(\d{1,2}:\d{2})', desc)
    transaction_time = time_match.group(1) if time_match else ""
    desc = re.sub(r'\|\s*\d{1,2}:\d{2}', '', desc)
    desc = re.sub(r'\+\s*\d+\s*C\b', '', desc)
    # Clean ICICI specific patterns: remove trailing numbers like "87 1,750.03 IN 100%"
    desc = re.sub(r'\d{1,3}\s+\d+(?:,\d{3})*(?:\.\d{1,2})?\s+IN\s+\d+%.*$', '', desc)
    desc = normalize_whitespace(desc)

    # Strip leading transaction-type prefixes defined in config (e.g. "EMI" column in HDFC PDFs)
    strip_prefixes = config.get("parsing", {}).get("strip_description_prefixes", [])
    for prefix in strip_prefixes:
        if re.match(rf"^{re.escape(prefix)}\s+", desc, re.IGNORECASE):
            desc = desc[len(prefix):].strip()
            break

    if not desc:
        desc = row_text.strip()

    if amount <= 0:
        return None

    return {
        "date":             date_str,
        "transaction_time": transaction_time,
        "cardholder":       config.get("cardholders", {}).get("primary", ""),
        "description":      desc,
        "reward_points":    reward_points,
        "amount":           amount,
        "is_credit":        is_credit,
        "source_pdf":       "",
        "earn_points":      True,
    }


def extract_bonus_points(pdf_text: str, config: dict, source_pdf: str, statement_date: str = "") -> list[dict]:
    # Normalise statement_date to dd/mm/yyyy so it's consistent with regular transactions
    if statement_date:
        statement_date = parse_date_string(statement_date)
    markers = config.get("parsing", {}).get("bonus_points_section_markers", []) or []
    bonus_pattern = config.get("parsing", {}).get("bonus_points_pattern")
    amount_regex = config.get("parsing", {}).get("amount_regex", r"\d+(?:,\d{2,3})*(?:\.\d{1,2})?")
    lines = [normalize_whitespace(line) for line in pdf_text.splitlines() if normalize_whitespace(line)]
    found = []

    # ── Strategy 1: detect numbered table rows directly ──────────────────────
    # Format: "N Description NNNN pts"  (e.g. "1 Reward Points_on_Grocery 690 pts")
    # This is more reliable than marker-based detection because the pattern is
    # unique to the rewards summary table and cannot match regular transactions.
    table_re = re.compile(r'^\d+\s+(\S.+?)\s+(\d[\d,]*)\s*pts\b', re.IGNORECASE)
    for line in lines:
        m = table_re.match(line)
        if m:
            desc = m.group(1).strip()
            pts = int(round(parse_amount(m.group(2))))
            if pts > 0:
                found.append((desc, pts))

    # ── Strategy 2: marker + bonus_pattern (config-driven) ───────────────────
    # Find the section whose header line most closely matches a marker
    # (prefer lines where the marker IS essentially the full line, not a substring
    # of a long sentence, to avoid hitting "REWARD POINTS CAN BE REDEEMED..." etc.)
    if not found and markers and bonus_pattern:
        section_start = None
        for idx, line in enumerate(lines):
            for marker in markers:
                if marker.upper() in line.upper():
                    if section_start is None or len(line) < len(lines[section_start]):
                        section_start = idx
        if section_start is not None:
            for bonus_line in lines[section_start + 1:]:
                if re.match(r'^total\b', bonus_line, re.IGNORECASE):
                    break
                match = re.search(bonus_pattern, bonus_line, re.IGNORECASE)
                if match:
                    points = match.groupdict().get("points") or match.group(1)
                    pts = int(round(parse_amount(points)))
                    if pts > 0:
                        found.append((bonus_line, pts))

    # ── Strategy 3: last-resort keyword scan ─────────────────────────────────
    if not found:
        for line in lines:
            if re.search(r"\b(bonus|reward|cashback)\b", line, re.IGNORECASE):
                amounts = re.findall(amount_regex, line)
                if amounts:
                    pts = int(round(parse_amount(amounts[-1])))
                    if pts > 0:
                        found.append((line, pts))

    bonus_txns = []
    seen_desc = set()
    for desc, pts in found:
        if desc in seen_desc:
            continue
        seen_desc.add(desc)
        bonus_txns.append({
            "date":             statement_date,
            "transaction_time": "",
            "cardholder":       config.get("cardholders", {}).get("primary", ""),
            "description":      desc,
            "reward_points":    pts,
            "amount":           0.0,
            "is_credit":        False,
            "source_pdf":       Path(source_pdf).name,
            "earn_points":      False,
            "category":         "Transfers & Payments",
            "subcategory":      "Cashback & Reversals",
            "notes":            "Bonus points summary",
            "skip_reward_calc": True,
        })
    return bonus_txns


def extract_transactions(pdf_text: str, config: dict, source_pdf: str, statement_date: str = "") -> list[dict]:
    """Extract transactions and bonus rewards from PDF text using config hints."""
    section = find_transaction_section(pdf_text, config)
    raw_rows = split_transaction_rows(section, config)

    transactions = []
    for row in raw_rows:
        txn = parse_transaction_row(row, config)
        if not txn:
            continue
        txn["source_pdf"] = Path(source_pdf).name
        transactions.append(txn)

    bonus_txns = extract_bonus_points(pdf_text, config, source_pdf, statement_date)
    transactions.extend(bonus_txns)
    logger.info(f"Extracted {len(transactions)} local transactions from {Path(source_pdf).name}")
    return transactions
