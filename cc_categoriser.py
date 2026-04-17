"""
cc_categoriser.py
-----------------
Categorises extracted transactions using:
  1. Hard-coded vendor rules from card config (fastest, most accurate)
  2. Vendor master CSV lookup (known vendors from history)
  3. Claude AI categorisation for unknown vendors (slowest, most flexible)

Updates the vendor master CSV with any newly categorised vendors.
"""

import csv
import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  VENDOR MASTER LOADER
# ─────────────────────────────────────────────

def load_vendor_master(vendor_master_path: str) -> dict:
    """
    Load vendor master CSV → dict keyed by uppercase description prefix.
    Returns: { "VENDOR NAME": {"category": ..., "subcategory": ..., "ai_guessed": ...} }
    """
    vendor_map = {}
    path = Path(vendor_master_path)
    if not path.exists():
        logger.warning(f"Vendor master not found: {vendor_master_path}")
        return vendor_map

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row.get("Transaction Description", "").strip().upper()
            if key:
                vendor_map[key] = {
                    "category":   row.get("Category", "Others"),
                    "subcategory": row.get("SubCategory", "Others"),
                    "ai_guessed": row.get("AI Guessed", "No").lower() == "yes",
                }
    logger.info(f"Loaded {len(vendor_map)} vendors from master")
    return vendor_map


def save_vendor_master(vendor_master_path: str, vendor_map: dict, new_vendors: dict):
    """
    Append new vendors to the vendor master CSV.
    new_vendors: { description: {category, subcategory, ai_guessed, spend} }
    """
    path = Path(vendor_master_path)
    fieldnames = ["Transaction Description", "Category", "SubCategory",
                  "AI Guessed", "Txn Count", "Total Spend (Rs.)"]

    # Load existing rows
    existing = {}
    if path.exists():
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing[row["Transaction Description"]] = row

    # Merge new
    for desc, v in new_vendors.items():
        if desc not in existing:
            existing[desc] = {
                "Transaction Description": desc,
                "Category":   v["category"],
                "SubCategory": v["subcategory"],
                "AI Guessed": "Yes" if v.get("ai_guessed") else "No",
                "Txn Count":  v.get("count", 1),
                "Total Spend (Rs.)": round(v.get("spend", 0), 2),
            }

    # Write back
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for desc, row in sorted(existing.items()):
            writer.writerow(row)

    logger.info(f"Vendor master updated — {len(new_vendors)} new vendors added")


# ─────────────────────────────────────────────
#  RULE-BASED CATEGORISATION
# ─────────────────────────────────────────────

def match_vendor_rule(description: str, vendor_rules: dict) -> Optional[tuple]:
    """
    Match a transaction description against config vendor_rules.
    Rules are keyword-based (substring match on uppercase description).
    Returns (category, subcategory, earn_points) or None.
    """
    desc_upper = description.upper()
    for keyword, mapping in vendor_rules.items():
        if keyword.upper() in desc_upper:
            category, subcategory, earn_points = mapping
            return category, subcategory, bool(earn_points)
    return None


def match_vendor_master(description: str, vendor_map: dict) -> Optional[tuple]:
    """
    Exact match on full description (uppercase) against loaded vendor master.
    Returns (category, subcategory, ai_guessed) or None.
    """
    key = description.strip().upper()
    if key in vendor_map:
        v = vendor_map[key]
        return v["category"], v["subcategory"], v["ai_guessed"]

    # Partial prefix match (first 40 chars) for vendor names that truncate
    key_short = key[:40]
    for vendor_key, v in vendor_map.items():
        if vendor_key[:40] == key_short:
            return v["category"], v["subcategory"], v["ai_guessed"]

    return None


# ─────────────────────────────────────────────
#  CLAUDE BATCH CATEGORISATION
# ─────────────────────────────────────────────

def categorise_unknown_vendors_via_claude(
    unknown_descs: list[str],
    config: dict,
    claude_client
) -> dict:
    """
    Batch-send unknown vendor descriptions to Claude for categorisation.
    Returns: { description: {category, subcategory, ai_guessed: True} }
    """
    if not unknown_descs:
        return {}

    # Build category list for the prompt
    cats = config.get("categories", [])
    cat_list = "\n".join(
        f"  {c['name']}: {', '.join(c['subcategories'])}"
        for c in cats
    )

    # Build list of descriptions
    desc_list = "\n".join(f"{i+1}. {d}" for i, d in enumerate(unknown_descs))

    prompt = f"""You are categorising credit card transaction descriptions for a personal finance tracker.

AVAILABLE CATEGORIES AND SUBCATEGORIES:
{cat_list}

TRANSACTION DESCRIPTIONS TO CATEGORISE:
{desc_list}

RULES:
1. Return ONLY a JSON array — no markdown, no explanation.
2. One object per transaction in the SAME ORDER as input.
3. Each object: {{"category": "...", "subcategory": "..."}}
4. Use ONLY the categories and subcategories listed above.
5. If truly unknown, use "Others" / "Others".
6. Common patterns:
   - IMPS/NEFT/AUTOPAY → Transfers & Payments / CC Bill Payment
   - IGST/GST charges → Travel / Forex & Fees
   - EMI entries (MER EMI, M-*) → infer from vendor (Pepperfry=Shopping/Home, MakemyTrip=Travel)
   - Insurance company names → Investments & Assets / Insurance
   - Hospital/clinic names → Health & Wellness / Medical & Hospital
   - Petrol pump names → Vehicle & Mobility / Fuel
   - Government entities → Taxes & Government

Return JSON array only:"""

    response = claude_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE).strip()

    try:
        results = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r'\[.*\]', raw, re.DOTALL)
        results = json.loads(m.group(0)) if m else []

    # Map back to descriptions
    categorised = {}
    for i, desc in enumerate(unknown_descs):
        if i < len(results) and isinstance(results[i], dict):
            categorised[desc] = {
                "category":   results[i].get("category", "Others"),
                "subcategory": results[i].get("subcategory", "Others"),
                "ai_guessed": True,
            }
        else:
            categorised[desc] = {"category": "Others", "subcategory": "Others", "ai_guessed": True}

    logger.info(f"Claude categorised {len(categorised)} unknown vendors")
    return categorised


# ─────────────────────────────────────────────
#  REWARD POINTS CALCULATION
# ─────────────────────────────────────────────

def calculate_reward_points(txn: dict, config: dict) -> tuple[int, float]:
    """
    Returns (reward_points, pct_reward) for a transaction.
    Uses stated points if available, else calculates from config rate.
    Zero-earn rules applied.
    """
    if txn.get("is_credit") or txn.get("amount", 0) <= 0:
        return 0, 0.0

    category   = txn.get("category", "")
    subcategory = txn.get("subcategory", "")
    description = txn.get("description", "").upper()
    amount     = txn.get("amount", 0)
    earn_points = txn.get("earn_points", True)

    rewards = config.get("rewards", {})
    zero_cats  = [c.upper() for c in rewards.get("zero_earn_categories", [])]
    zero_subs  = [s.upper() for s in rewards.get("zero_earn_subcategories", [])]
    zero_kws   = [k.upper() for k in rewards.get("zero_earn_keywords", [])]

    # Check zero-earn rules
    is_zero = (
        not earn_points or
        category.upper() in zero_cats or
        subcategory.upper() in zero_subs or
        any(kw in description for kw in zero_kws)
    )

    if is_zero:
        return 0, 0.0

    # Use stated points if provided and reasonable
    stated = txn.get("reward_points", 0) or 0
    if stated > 0:
        pct = round((stated / amount) * 100, 2) if amount > 0 else 0.0
        return stated, pct

    # Calculate from config rate
    rate = rewards.get("standard_rate", 3.33)
    per  = rewards.get("standard_per", 100)
    pts  = int((amount / per) * rate)
    pct  = round((pts / amount) * 100, 2) if amount > 0 else 0.0
    return pts, pct


# ─────────────────────────────────────────────
#  MAIN CATEGORISE PIPELINE
# ─────────────────────────────────────────────

def categorise_transactions(
    transactions: list[dict],
    config: dict,
    vendor_map: dict,
    claude_client,
    vendor_master_path: str
) -> list[dict]:
    """
    Full categorisation pipeline for a list of raw transactions.
    Returns enriched transactions with category, subcategory, reward info.
    """
    vendor_rules = config.get("vendor_rules", {})
    categorised_txns = []
    unknown_descs   = []      # collect unknowns for batch Claude call
    unknown_indices = []

    # Pass 1: rule-based + vendor master
    for i, txn in enumerate(transactions):
        desc = txn.get("description", "")
        result = None
        source = None

        # 1a. Hard-coded vendor rules (highest priority)
        rule = match_vendor_rule(desc, vendor_rules)
        if rule:
            cat, sub, earn = rule
            result = {"category": cat, "subcategory": sub,
                      "earn_points": earn, "ai_guessed": False}
            source = "rule"

        # 1b. Vendor master lookup
        if not result:
            master = match_vendor_master(desc, vendor_map)
            if master:
                cat, sub, ai = master
                result = {"category": cat, "subcategory": sub,
                          "earn_points": True, "ai_guessed": ai}
                source = "master"

        if result:
            txn.update(result)
            txn["notes"] = "AI-guessed" if result["ai_guessed"] else ""
        else:
            unknown_descs.append(desc)
            unknown_indices.append(i)

        categorised_txns.append(txn)

    logger.info(
        f"Categorised via rules/master: {len(transactions)-len(unknown_descs)} | "
        f"Unknown (for Claude): {len(unknown_descs)}"
    )

    # Pass 2: batch Claude categorisation for unknowns
    if unknown_descs:
        # Batch in groups of 50 to stay within token limits
        batch_size = 50
        all_claude_results = {}
        for start in range(0, len(unknown_descs), batch_size):
            batch = unknown_descs[start:start + batch_size]
            results = categorise_unknown_vendors_via_claude(batch, config, claude_client)
            all_claude_results.update(results)

        # Apply Claude results
        new_vendors = {}
        for idx, desc in zip(unknown_indices, unknown_descs):
            cr = all_claude_results.get(desc, {"category": "Others", "subcategory": "Others", "ai_guessed": True})
            categorised_txns[idx].update(cr)
            categorised_txns[idx]["earn_points"] = True
            categorised_txns[idx]["notes"] = "AI-guessed"
            # Collect for vendor master update
            amt = categorised_txns[idx].get("amount", 0)
            if desc not in new_vendors:
                new_vendors[desc] = {"count": 0, "spend": 0.0, **cr}
            new_vendors[desc]["count"] += 1
            new_vendors[desc]["spend"] += amt

        # Update vendor master with new entries
        if new_vendors:
            save_vendor_master(vendor_master_path, vendor_map, new_vendors)

    # Pass 3: calculate reward points
    for txn in categorised_txns:
        pts, pct = calculate_reward_points(txn, config)
        txn["reward_points"] = pts
        txn["pct_reward"]    = pct

    return categorised_txns
