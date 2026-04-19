"""
cc_processor.py
---------------
Orchestrates the full pipeline for a single new statement PDF:
  1. Extract PDF text
  2. Detect card config
  3. Extract transactions via Claude
  4. Categorise transactions
  5. Deduplicate against existing ledger
  6. Append to ledger
  7. Generate insights report
  8. Regenerate my-cc-report.html

Usage (standalone):
  python cc_processor.py /path/to/statement.pdf

Usage (called by watcher):
  from cc_processor import process_statement
  process_statement("/path/to/statement.pdf", settings)
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from datetime import datetime

import yaml

# ── import sibling modules ──
sys.path.insert(0, str(Path(__file__).parent))
from cc_extractor import (
    extract_pdf_text,
    detect_card_config,
    extract_statement_metadata,
    extract_transactions,
)
from cc_categoriser import (
    load_vendor_master,
    categorise_transactions,
)
from cc_ledger import (
    load_ledger,
    deduplicate,
    txn_to_ledger_row,
    append_to_ledger,
    summarise_new_transactions,
)
from cc_insights import generate_insights_via_claude, write_insights_report
from cc_report import regenerate_report

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  CONFIG LOADER
# ─────────────────────────────────────────────

def load_all_configs(config_dir: str) -> dict:
    """Load all YAML card configs from config directory."""
    configs = {}
    config_path = Path(config_dir)
    for yaml_file in config_path.glob("*.yaml"):
        if yaml_file.name.startswith("_"):
            continue  # skip templates
        try:
            with open(yaml_file, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            card_id = cfg.get("card", {}).get("id", yaml_file.stem)
            configs[card_id] = cfg
            logger.info(f"Loaded config: {card_id} from {yaml_file.name}")
        except Exception as e:
            logger.warning(f"Failed to load config {yaml_file}: {e}")
    return configs


def load_settings(settings_path: str) -> dict:
    """Load settings.yaml — paths and API key."""
    with open(settings_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def append_unidentified_to_todo(output_dir: str, transactions: list[dict], source_pdf: str):
    """Append unidentified transaction descriptions to category_todo.csv for manual review."""
    import csv
    todo_path = Path(output_dir) / "category_todo.csv"
    
    # Create file with headers if it doesn't exist
    if not todo_path.exists():
        with open(todo_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Transaction Description", "Amount", "Date", "Source PDF", "Added On"])
    
    # Append unidentified transactions
    with open(todo_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for txn in transactions:
            if txn.get("category") == "UNIDENTIFIED":
                writer.writerow([
                    txn.get("description", ""),
                    txn.get("amount", 0),
                    txn.get("date", ""),
                    source_pdf,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ])
    
    logger.info(f"Appended {sum(1 for txn in transactions if txn.get('category') == 'UNIDENTIFIED')} unidentified transactions to {todo_path}")


# ─────────────────────────────────────────────
#  CLAUDE CLIENT FACTORY
# ─────────────────────────────────────────────

def make_claude_client(api_key: str):
    """Create Anthropic client using requests (no SDK needed)."""
    import requests

    class ClaudeClient:
        def __init__(self, key):
            self.api_key = key
            self.messages = self  # for .messages.create() pattern

        def create(self, model, max_tokens, messages, **kwargs):
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            body = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": messages,
            }
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=body,
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()

            class Response:
                pass

            class Content:
                pass

            r = Response()
            c = Content()
            c.text = data["content"][0]["text"]
            r.content = [c]
            return r

    return ClaudeClient(api_key)


# ─────────────────────────────────────────────
#  PROCESSED FILES TRACKER
# ─────────────────────────────────────────────

def load_processed_log(log_path: str) -> set:
    """Load set of already-processed PDF filenames."""
    path = Path(log_path)
    if not path.exists():
        return set()
    with open(path) as f:
        return set(line.strip() for line in f if line.strip())


def mark_processed(log_path: str, pdf_name: str):
    """Append a PDF filename to the processed log."""
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as f:
        f.write(pdf_name + "\n")


# ─────────────────────────────────────────────
#  MAIN PIPELINE
# ─────────────────────────────────────────────

def process_statement(pdf_path: str, settings: dict) -> dict:
    """
    Full processing pipeline for one PDF.
    Returns a result dict with status and paths.
    """
    pdf_path = Path(pdf_path)
    start_time = time.time()
    logger.info(f"{'='*60}")
    logger.info(f"Processing: {pdf_path.name}")
    logger.info(f"{'='*60}")

    # Paths from settings
    config_dir       = settings["paths"]["config_dir"]
    ledger_path      = settings["paths"]["ledger_csv"]
    vendor_master_path = settings["paths"]["vendor_master_csv"]
    output_dir       = settings["paths"]["output_dir"]
    report_path      = settings["paths"]["report_html"]
    processed_log    = settings["paths"]["processed_log"]
    api_key          = settings["api_key"]

    result = {
        "pdf": str(pdf_path),
        "status": "failed",
        "new_transactions": 0,
        "skipped_duplicates": 0,
        "insights_path": None,
        "report_path": None,
        "elapsed_seconds": 0,
    }

    try:
        # ── 0. Load configs early (needed for password attempts) ──
        logger.info("Loading card configs...")
        all_configs = load_all_configs(config_dir)
        if not all_configs:
            raise ValueError(f"No card configs found in {config_dir}")
        
        # ── 1. Extract PDF text ──
        logger.info("Step 1/7: Extracting PDF text...")
        from cc_extractor import PasswordError
        try:
            # Try without password first
            pdf_text = extract_pdf_text(str(pdf_path))
        except PermissionError as pe:
            # File is locked or not accessible — don't mark as processed, will retry
            logger.error(f"❌ Cannot access {pdf_path.name} — file is locked or not accessible")
            logger.error(f"   {pe}")
            result["status"] = "file_locked"
            result["error"] = str(pe)
            result["elapsed_seconds"] = round(time.time() - start_time, 1)
            # Do NOT mark as processed — will retry next time
            return result
        except PasswordError as pe:
            # Try passwords from all available configs
            logger.info("PDF is password-protected, trying passwords from configs...")
            pdf_text = None
            passwords_tried = 0
            
            for card_id, cfg in all_configs.items():
                passwords = cfg.get("passwords", [])
                for pwd in passwords:
                    passwords_tried += 1
                    try:
                        logger.info(f"  Trying password from {card_id}...")
                        pdf_text = extract_pdf_text(str(pdf_path), passwords=[pwd])
                        logger.info(f"✅ Successfully extracted with password from {card_id}")
                        break
                    except (PasswordError, Exception):
                        continue
                if pdf_text:
                    break
            
            if not pdf_text:
                logger.error(f"❌ Failed to extract {pdf_path.name} — tried {passwords_tried} password(s) from all configs")
                result["status"] = "password_failed"
                result["error"] = f"PDF is password-protected and all {passwords_tried} password attempts failed"
                result["elapsed_seconds"] = round(time.time() - start_time, 1)
                # Do NOT mark as processed — will retry next time
                return result
        except Exception as e:
            logger.error(f"Failed to extract PDF text: {e}")
            raise
        
        if not pdf_text.strip():
            raise ValueError(f"No text extracted from {pdf_path.name} — may be scanned/image PDF")

        # ── 2. Detect card config ──
        logger.info("Step 2/7: Detecting card config...")

        config = detect_card_config(pdf_text, all_configs)
        if not config:
            # Fall back to first available config
            config = list(all_configs.values())[0]
            logger.warning(f"No config matched — falling back to {config['card']['id']}")

        card_id   = config["card"]["id"]
        card_name = config["card"]["name"]
        logger.info(f"Using config: {card_name}")

        # ── 3. Extract statement metadata ──
        stmt_meta = extract_statement_metadata(pdf_text, config)
        stmt_meta["source_pdf"] = pdf_path.name
        logger.info(f"Statement date: {stmt_meta.get('statement_date', 'unknown')}")

        # ── 4. Extract transactions locally ──
        logger.info("Step 3/7: Extracting transactions locally...")
        claude = make_claude_client(api_key) if api_key else None
        raw_transactions = extract_transactions(pdf_text, config, str(pdf_path), stmt_meta.get("statement_date", ""))
        logger.info(f"Raw transactions extracted: {len(raw_transactions)}")

        if not raw_transactions:
            raise ValueError("No transactions extracted — check PDF format")

        # ── 5. Load existing data ──
        logger.info("Step 4/7: Loading existing ledger and vendor master...")
        existing_rows = load_ledger(ledger_path)
        vendor_map    = load_vendor_master(vendor_master_path)

        # ── 6. Deduplicate ──
        logger.info("Step 5/7: Deduplicating...")
        to_add, skipped = deduplicate(raw_transactions, existing_rows)
        result["skipped_duplicates"] = len(skipped)

        if not to_add:
            logger.warning("All transactions already in ledger — nothing new to add")
            result["status"] = "already_processed"
            result["elapsed_seconds"] = round(time.time() - start_time, 1)
            mark_processed(processed_log, pdf_path.name)
            return result

        # ── 7. Categorise ──
        logger.info(f"Step 5/7: Categorising {len(to_add)} new transactions...")
        try:
            categorised = categorise_transactions(
                to_add, config, vendor_map, claude, vendor_master_path
            )
        except Exception as e:
            logger.error(f"Categorisation failed: {e}")
            # Fallback: mark all transactions as UNIDENTIFIED
            for txn in to_add:
                if not txn.get("category"):
                    txn.update({
                        "category": "UNIDENTIFIED",
                        "subcategory": "UNIDENTIFIED", 
                        "earn_points": True,
                        "ai_guessed": False,
                        "notes": "Categorisation failed"
                    })
            categorised = to_add
            # Append unidentified transactions to todo list for manual review
            append_unidentified_to_todo(output_dir, categorised, pdf_path.name)

        # ── 8. Convert to ledger rows ──
        new_ledger_rows = [txn_to_ledger_row(txn, config) for txn in categorised]
        result["new_transactions"] = len(new_ledger_rows)

        # ── 9. Append to ledger ──
        logger.info(f"Step 6/7: Appending {len(new_ledger_rows)} rows to ledger...")
        all_rows = append_to_ledger(ledger_path, existing_rows, new_ledger_rows)

        # ── 10. Generate insights ──
        logger.info("Step 7/7: Generating insights...")
        summary = summarise_new_transactions(new_ledger_rows)
        insights_path = None
        if claude:
            try:
                insights_text = generate_insights_via_claude(
                    summary, all_rows, new_ledger_rows, stmt_meta, config, claude
                )
                insights_path = write_insights_report(
                    insights_text, summary, new_ledger_rows, stmt_meta, config, output_dir
                )
                result["insights_path"] = insights_path
            except Exception as e:
                logger.error(f"Insights generation failed: {e}")
                logger.info("Continuing without insights report")
                insights_path = None
                result["insights_path"] = None
        else:
            logger.info("Skipping insights generation (no API key)")
            insights_path = None
            result["insights_path"] = None

        # ── 11. Regenerate report ──
        rpt = regenerate_report(ledger_path, config, report_path)
        result["report_path"] = rpt

        # ── 12. Mark as processed ──
        mark_processed(processed_log, pdf_path.name)

        result["status"] = "success"
        result["elapsed_seconds"] = round(time.time() - start_time, 1)

        logger.info(f"✅ Done in {result['elapsed_seconds']}s")
        logger.info(f"   New transactions : {result['new_transactions']}")
        logger.info(f"   Duplicates skipped: {result['skipped_duplicates']}")
        logger.info(f"   Insights → {insights_path}")
        logger.info(f"   Report   → {report_path}")

        return result

    except Exception as e:
        logger.exception(f"Pipeline failed for {pdf_path.name}: {e}")
        result["status"]  = "failed"
        result["error"]   = str(e)
        result["elapsed_seconds"] = round(time.time() - start_time, 1)
        return result


# ─────────────────────────────────────────────
#  CLI ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )

    if len(sys.argv) < 2:
        print("Usage: python cc_processor.py <pdf_path> [settings.yaml]")
        sys.exit(1)

    pdf   = sys.argv[1]
    cfg_f = sys.argv[2] if len(sys.argv) > 2 else str(Path(__file__).parent / "settings.yaml")

    settings = load_settings(cfg_f)
    result   = process_statement(pdf, settings)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "success" else 1)
