"""
cc_insights.py
--------------
Generates a natural-language insights summary for every new statement processed.
Writes to: output/insights_YYYY-MM_<card>.md
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def fc(n: float) -> str:
    """Format currency for display."""
    if n >= 10_000_000:
        return f"₹{n/10_000_000:.2f}Cr"
    if n >= 100_000:
        return f"₹{n/100_000:.2f}L"
    if n >= 1_000:
        return f"₹{n/1_000:.1f}K"
    return f"₹{n:.0f}"


def fp(n: int) -> str:
    """Format points for display."""
    return f"{n/1000:.1f}K pts" if n >= 1000 else f"{n} pts"


def generate_insights_via_claude(
    new_summary: dict,
    all_rows: list[dict],
    new_rows: list[dict],
    statement_meta: dict,
    config: dict,
    claude_client
) -> str:
    """
    Uses Claude to generate a concise, insightful advisory from:
    - The new statement's transactions
    - Historical context from the full ledger
    """
    card_name   = config.get("card", {}).get("name", "Credit Card")
    cardholder  = config.get("cardholders", {}).get("primary", "Cardholder")
    std_rate    = config.get("rewards", {}).get("standard_rate", 3.33)

    # Build historical context
    all_debits = [r for r in all_rows if r.get("Is Credit") == "FALSE"
                  and float(r.get("Amount (Rs.)", 0)) > 0]
    hist_total = sum(float(r.get("Amount (Rs.)", 0)) for r in all_debits)
    hist_pts   = sum(int(r.get("Reward Points", 0)) for r in all_debits)

    # MOM context: last 3 months
    months_seen = sorted(set(
        f"{r.get('Year')}-{int(r.get('Month',0)):02d}" for r in all_debits
        if r.get("Year") and r.get("Month")
    ), reverse=True)[:4]
    mom_context = []
    for mk in months_seen[1:4]:
        yr, mo = mk.split("-")
        m_rows = [r for r in all_debits
                  if str(r.get("Year")) == yr and str(r.get("Month")).zfill(2) == mo]
        m_amt  = sum(float(r.get("Amount (Rs.)", 0)) for r in m_rows)
        mom_context.append(f"  {mk}: {fc(m_amt)}")

    # New statement details
    ns = new_summary
    top_cats_str = "\n".join(
        f"  {cat}: {fc(amt)}" for cat, amt in ns.get("top_categories", [])
    )
    top_txns_str = "\n".join(
        f"  {t['date']} | {t['desc'][:45]} | {t['cat']} | {fc(t['amt'])}"
        for t in ns.get("top_transactions", [])
    )

    prompt = f"""You are a sharp personal finance advisor reviewing a credit card statement for {cardholder}.

CARD: {card_name}
STATEMENT DATE: {statement_meta.get('statement_date', 'Unknown')}

NEW STATEMENT SUMMARY:
- Transactions: {ns['debit_count']} debits, {ns['credit_count']} credits
- Total Spend: {fc(ns['total_spend'])}
- Points Earned: {fp(ns['total_points'])} ({ns['reward_rate']} pts/₹100 vs standard {std_rate}/₹100)
- Zero-Earn Spend: {fc(ns['zero_earn_spend'])} across {ns['zero_earn_count']} transactions

TOP CATEGORIES THIS STATEMENT:
{top_cats_str}

TOP 5 TRANSACTIONS THIS STATEMENT:
{top_txns_str}

RECENT MONTHLY CONTEXT (prior months):
{chr(10).join(mom_context) if mom_context else "  No prior history"}

ALL-TIME TOTALS (for comparison):
- Total spend: {fc(hist_total)}
- Total points: {fp(hist_pts)}
- Avg reward rate: {round(hist_pts/hist_total*100, 2) if hist_total > 0 else 0} pts/₹100

Write a concise advisory (250–400 words) covering:
1. **Spend overview** — how does this month compare to recent months? Any notable spikes?
2. **Top categories** — what drove spend this period? Anything unusual?
3. **Points performance** — is the reward rate healthy? Any significant zero-earn leakage?
4. **Notable transactions** — call out anything large, unusual, or worth flagging.
5. **One actionable tip** — one specific thing to optimise next month (e.g. route a specific spend through SmartBuy, consolidate a category, pay before due date to avoid interest).

Be direct, specific with numbers, and avoid generic advice. Write in second person ("you spent...", "your reward rate...").
Format with markdown headers for each section."""

    response = claude_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


def write_insights_report(
    insights_text: str,
    new_summary: dict,
    new_rows: list[dict],
    statement_meta: dict,
    config: dict,
    output_dir: str
) -> str:
    """
    Write the insights markdown file.
    Returns the path to the written file.
    """
    card_id   = config.get("card", {}).get("id", "card")
    stmt_date = statement_meta.get("statement_date", datetime.now().strftime("%d/%m/%Y"))
    # Parse to YYYY-MM for filename
    try:
        from datetime import datetime as dt
        parsed = dt.strptime(stmt_date, "%d/%m/%Y")
        date_slug = parsed.strftime("%Y-%m")
    except Exception:
        date_slug = datetime.now().strftime("%Y-%m")

    ns = new_summary
    filename = f"insights_{date_slug}_{card_id}.md"
    output_path = Path(output_dir) / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build new transactions table
    new_debits = [r for r in new_rows if r.get("Is Credit") == "FALSE"]
    rows_table = "\n".join(
        f"| {r['Date']} | {r['Transaction Description'][:45]} | "
        f"{r['Category']} / {r['SubCategory']} | "
        f"₹{float(r.get('Amount (Rs.)',0)):,.0f} | {r.get('Reward Points',0)} |"
        for r in sorted(new_debits,
                        key=lambda x: -float(x.get("Amount (Rs.)", 0)))
    )

    content = f"""# Statement Insights — {stmt_date}
**Card:** {config.get('card', {}).get('name', 'Credit Card')}
**Processed:** {datetime.now().strftime('%d %b %Y %H:%M')}
**Source PDF:** {statement_meta.get('source_pdf', 'Unknown')}

---

## Advisory

{insights_text}

---

## Statement Summary

| Metric | Value |
|--------|-------|
| New Transactions | {ns['total_transactions']} |
| Debit Transactions | {ns['debit_count']} |
| Total Spend | ₹{ns['total_spend']:,.2f} |
| Points Earned | {ns['total_points']:,} |
| Reward Rate | {ns['reward_rate']} pts/₹100 |
| Zero-Earn Spend | ₹{ns['zero_earn_spend']:,.2f} ({ns['zero_earn_count']} txns) |

## Top Categories

| Category | Spend |
|----------|-------|
{"".join(f"| {cat} | ₹{amt:,.0f} |" + chr(10) for cat, amt in ns.get('top_categories', []))}

## All New Transactions (debits, sorted by amount)

| Date | Description | Category / Subcategory | Amount | Points |
|------|-------------|----------------------|--------|--------|
{rows_table}
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"Insights written → {output_path}")
    return str(output_path)
