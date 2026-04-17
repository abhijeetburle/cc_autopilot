"""
cc_ledger.py
------------
Manages the transactions_master CSV:
  - Load existing transactions
  - Deduplicate new transactions against existing
  - Append new rows
  - Parse dates into Year/Month/Day fields
"""

import csv
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

FIELDNAMES = [
    "Year", "Month", "Day", "Date", "Time", "Cardholder",
    "Transaction Description", "Category", "SubCategory",
    "Reward Points", "Amount (Rs.)", "Is Credit",
    "% Reward", "Notes", "Source PDF", "Bank", "Card"
]


# ─────────────────────────────────────────────
#  LOAD
# ─────────────────────────────────────────────

def load_ledger(ledger_path: str) -> list[dict]:
    """Load existing transactions master CSV."""
    path = Path(ledger_path)
    if not path.exists():
        logger.info(f"No existing ledger at {ledger_path} — starting fresh")
        return []
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    logger.info(f"Loaded {len(rows)} existing transactions from ledger")
    return rows


def build_dedup_key(row: dict) -> tuple:
    """
    Deduplication key: (Date, Time, first-30-chars of description, amount).
    Time distinguishes same-day same-amount same-vendor transactions.
    Normalises amount to float for consistent comparison.
    """
    try:
        amt = float(row.get("Amount (Rs.)", 0))
    except (ValueError, TypeError):
        amt = 0.0
    desc = str(row.get("Transaction Description", "") or
               row.get("description", "")).strip()[:30]
    date = str(row.get("Date", "") or row.get("date", "")).strip()
    time = str(row.get("Time", "") or row.get("transaction_time", "")).strip()
    return (date, time, desc, amt)


# ─────────────────────────────────────────────
#  DEDUPLICATE
# ─────────────────────────────────────────────

def deduplicate(
    new_transactions: list[dict],
    existing_rows: list[dict]
) -> tuple[list[dict], list[dict]]:
    """
    Compare new_transactions against existing_rows.
    Returns (to_add, skipped).
    """
    existing_keys = {build_dedup_key(r) for r in existing_rows}

    to_add, skipped = [], []
    seen_new = set()

    for txn in new_transactions:
        # Build key from raw txn dict
        try:
            amt = float(txn.get("amount", 0))
        except (ValueError, TypeError):
            amt = 0.0
        if txn.get("is_credit"):
            amt = -abs(amt)

        desc = str(txn.get("description", "")).strip()[:30]
        date = str(txn.get("date", "")).strip()
        time = str(txn.get("transaction_time", "")).strip()
        key  = (date, time, desc, abs(amt))

        if key in existing_keys or key in seen_new:
            skipped.append(txn)
        else:
            to_add.append(txn)
            seen_new.add(key)

    if skipped:
        print(f"\n  Duplicates skipped ({len(skipped)}):")
        for txn in skipped:
            amt = abs(float(txn.get("amount", 0)))
            print(f"    [DUP] {txn.get('date', ''):>10}  {txn.get('description', '')[:40]:<40}  ₹{amt:>10.2f}")
        print()
    logger.info(f"New: {len(to_add)} | Duplicates skipped: {len(skipped)}")
    return to_add, skipped


# ─────────────────────────────────────────────
#  DATE PARSING
# ─────────────────────────────────────────────

def parse_date(date_str: str, date_format: str = "%d/%m/%Y") -> tuple[int, int, int]:
    """Parse date string → (year, month, day). Tries multiple formats."""
    formats = [
        date_format,
        "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y",
        "%Y-%m-%d", "%d %b %Y", "%d %b, %Y", "%d %B %Y", "%d %B, %Y", "%d/%m/%y",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.year, dt.month, dt.day
        except ValueError:
            continue
    logger.warning(f"Could not parse date: {date_str!r}")
    return 0, 0, 0


# ─────────────────────────────────────────────
#  CONVERT TO LEDGER ROW
# ─────────────────────────────────────────────

def txn_to_ledger_row(txn: dict, config: dict) -> dict:
    """Convert a categorised transaction dict to a ledger CSV row."""
    date_fmt = config.get("parsing", {}).get("date_format", "%d/%m/%Y")
    date_str = str(txn.get("date", "")).strip()
    year, month, day = parse_date(date_str, date_fmt)

    amt = abs(float(txn.get("amount", 0)))
    is_credit = bool(txn.get("is_credit", False))
    final_amt = -amt if is_credit else amt

    # Cardholder normalisation
    cardholder = str(txn.get("cardholder", "")).strip()
    primary = config.get("cardholders", {}).get("primary", "")
    if not cardholder and primary:
        cardholder = primary

    pts  = int(txn.get("reward_points", 0) or 0)
    pct  = float(txn.get("pct_reward", 0) or 0)
    cat  = txn.get("category", "Others")
    sub  = txn.get("subcategory", "Others")
    notes = txn.get("notes", "")
    src   = txn.get("source_pdf", "")
    bank  = config.get("card", {}).get("bank", "Unknown Bank")
    card  = config.get("card", {}).get("name", "Unknown Card")

    return {
        "Year":                   year,
        "Month":                  month,
        "Day":                    day,
        "Date":                   date_str,
        "Time":                   str(txn.get("transaction_time", "") or "").strip(),
        "Cardholder":             cardholder,
        "Transaction Description": txn.get("description", ""),
        "Category":               cat,
        "SubCategory":            sub,
        "Reward Points":          pts,
        "Amount (Rs.)":           final_amt,
        "Is Credit":              "TRUE" if is_credit else "FALSE",
        "% Reward":               pct,
        "Notes":                  notes,
        "Source PDF":             src,
        "Bank":                   bank,
        "Card":                   card,
    }


# ─────────────────────────────────────────────
#  SAVE
# ─────────────────────────────────────────────

def append_to_ledger(
    ledger_path: str,
    existing_rows: list[dict],
    new_rows: list[dict]
) -> list[dict]:
    """
    Append new_rows to existing_rows, sort by date, write to ledger CSV.
    Returns combined sorted rows.
    """
    all_rows = existing_rows + new_rows

    # Sort by Year, Month, Day
    def sort_key(r):
        try:
            return (int(r.get("Year", 0)), int(r.get("Month", 0)), int(r.get("Day", 0)))
        except (ValueError, TypeError):
            return (0, 0, 0)

    all_rows.sort(key=sort_key)

    Path(ledger_path).parent.mkdir(parents=True, exist_ok=True)
    with open(ledger_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(all_rows)

    logger.info(f"Ledger saved: {len(all_rows)} total rows → {ledger_path}")
    return all_rows


# ─────────────────────────────────────────────
#  SUMMARY OF NEW TRANSACTIONS
# ─────────────────────────────────────────────

def summarise_new_transactions(new_rows: list[dict]) -> dict:
    """Build a summary dict of the newly added transactions for insights generation."""
    debits  = [r for r in new_rows if r.get("Is Credit") == "FALSE"]
    credits = [r for r in new_rows if r.get("Is Credit") == "TRUE"]

    total_spend = sum(float(r.get("Amount (Rs.)", 0)) for r in debits)
    total_pts   = sum(int(r.get("Reward Points", 0)) for r in debits)

    by_cat = {}
    for r in debits:
        cat = r.get("Category", "Others")
        by_cat[cat] = by_cat.get(cat, 0) + float(r.get("Amount (Rs.)", 0))

    top_cats = sorted(by_cat.items(), key=lambda x: -x[1])[:5]
    top_spend = sorted(debits, key=lambda x: -float(x.get("Amount (Rs.)", 0)))[:5]
    zero_earn = [r for r in debits if int(r.get("Reward Points", 0)) == 0 and
                 float(r.get("Amount (Rs.)", 0)) > 0]

    return {
        "total_transactions": len(new_rows),
        "debit_count":        len(debits),
        "credit_count":       len(credits),
        "total_spend":        round(total_spend, 2),
        "total_points":       total_pts,
        "reward_rate":        round((total_pts / total_spend * 100), 2) if total_spend > 0 else 0,
        "top_categories":     top_cats,
        "top_transactions":   [
            {"date": r["Date"], "desc": r["Transaction Description"],
             "cat": r["Category"], "amt": float(r["Amount (Rs.)"])}
            for r in top_spend
        ],
        "zero_earn_spend":    round(sum(float(r.get("Amount (Rs.)", 0)) for r in zero_earn), 2),
        "zero_earn_count":    len(zero_earn),
    }
