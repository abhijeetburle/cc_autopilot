"""
watch_statements.py
-------------------
Watches a folder for new credit card statement PDFs and automatically
triggers the full processing pipeline when one arrives.

Setup:
  1. Edit settings.yaml to set your paths and API key
  2. Run:  python watch_statements.py
  3. Drop any statement PDF into the watch folder — done.

Requirements:
  pip install watchdog pdfplumber pyyaml
  (requests is part of stdlib-adjacent packages, usually available)
"""

import logging
import os
import sys
import time
from pathlib import Path
from datetime import datetime

import yaml

# ── try watchdog, fall back to polling ──
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileCreatedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False

sys.path.insert(0, str(Path(__file__).parent))
from cc_processor import process_statement, load_settings, load_processed_log, mark_processed

# ─────────────────────────────────────────────
#  LOGGING SETUP
# ─────────────────────────────────────────────

def setup_logging(log_dir: str):
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"cc_autopilot_{datetime.now().strftime('%Y-%m-%d')}.log"

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)-20s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # File handler
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    return logging.getLogger("watcher")


# ─────────────────────────────────────────────
#  PDF HANDLER
# ─────────────────────────────────────────────

def should_process(pdf_path: str, processed_log: str) -> bool:
    """Return True if this PDF hasn't been processed yet."""
    name = Path(pdf_path).name
    already_done = load_processed_log(processed_log)
    return name not in already_done


def handle_new_pdf(pdf_path: str, settings: dict, logger):
    """Called whenever a new PDF is detected."""
    processed_log = settings["paths"]["processed_log"]

    # Wait briefly for file write to complete
    time.sleep(2)

    if not Path(pdf_path).exists():
        logger.warning(f"File disappeared before processing: {pdf_path}")
        return

    if not should_process(pdf_path, processed_log):
        logger.info(f"Already processed — skipping: {Path(pdf_path).name}")
        return

    logger.info(f"🆕 New statement detected: {Path(pdf_path).name}")
    logger.info("Starting pipeline...")

    result = process_statement(pdf_path, settings)

    if result["status"] == "success":
        logger.info(f"✅ SUCCESS — {result['new_transactions']} new transactions added")
        logger.info(f"   Insights: {result.get('insights_path', 'N/A')}")
        logger.info(f"   Report:   {result.get('report_path', 'N/A')}")

        # Print a brief summary to console
        print("\n" + "═"*60)
        print(f"  ✅ {Path(pdf_path).name} processed successfully")
        print(f"  📊 {result['new_transactions']} new transactions added")
        print(f"  📝 Insights → {result.get('insights_path', 'N/A')}")
        print(f"  📈 Report   → {result.get('report_path', 'N/A')}")
        print("═"*60 + "\n")

    elif result["status"] == "already_processed":
        logger.info(f"ℹ️  All transactions already in ledger — no new data")

    else:
        logger.error(f"❌ FAILED: {result.get('error', 'Unknown error')}")
        print(f"\n❌ Failed to process {Path(pdf_path).name}: {result.get('error', 'Unknown error')}\n")


# ─────────────────────────────────────────────
#  WATCHDOG HANDLER
# ─────────────────────────────────────────────

if WATCHDOG_AVAILABLE:
    class PDFHandler(FileSystemEventHandler):
        def __init__(self, settings, logger):
            self.settings = settings
            self.logger   = logger
            super().__init__()

        def on_created(self, event):
            if event.is_directory:
                return
            path = event.src_path
            if path.lower().endswith(".pdf"):
                handle_new_pdf(path, self.settings, self.logger)

        def on_moved(self, event):
            # Also fires when a file is renamed/moved INTO the watch folder
            if event.is_directory:
                return
            if event.dest_path.lower().endswith(".pdf"):
                handle_new_pdf(event.dest_path, self.settings, self.logger)


# ─────────────────────────────────────────────
#  POLLING FALLBACK
# ─────────────────────────────────────────────

def poll_folder(watch_dir: str, settings: dict, logger, interval: int = 10):
    """Simple polling-based watcher if watchdog unavailable."""
    watch_path = Path(watch_dir)
    seen = set(watch_path.glob("*.pdf"))
    logger.info(f"Polling {watch_dir} every {interval}s (watchdog not available)")

    while True:
        time.sleep(interval)
        current = set(watch_path.glob("*.pdf"))
        new_pdfs = current - seen
        for pdf in sorted(new_pdfs):
            handle_new_pdf(str(pdf), settings, logger)
        seen = current


# ─────────────────────────────────────────────
#  STARTUP: process any existing unprocessed PDFs
# ─────────────────────────────────────────────

def process_existing_pdfs(watch_dir: str, settings: dict, logger):
    """
    On startup, check the watch folder for PDFs that haven't been processed yet.
    Useful when the watcher was offline and PDFs accumulated.
    """
    watch_path = Path(watch_dir)
    processed_log = settings["paths"]["processed_log"]
    all_pdfs = sorted(watch_path.glob("*.pdf"))

    pending = [p for p in all_pdfs if should_process(str(p), processed_log)]
    if not pending:
        logger.info("No unprocessed PDFs in watch folder")
        return

    logger.info(f"Found {len(pending)} unprocessed PDFs — processing on startup...")
    for pdf in pending:
        handle_new_pdf(str(pdf), settings, logger)


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def main():
    settings_path = Path(__file__).parent / "settings.yaml"
    if len(sys.argv) > 1:
        settings_path = sys.argv[1]

    if not Path(settings_path).exists():
        print(f"❌ settings.yaml not found at {settings_path}")
        print("   Copy settings.yaml.example and fill in your paths and API key.")
        sys.exit(1)

    settings = load_settings(str(settings_path))
    log_dir  = settings["paths"].get("log_dir", str(Path(__file__).parent / "logs"))
    logger   = setup_logging(log_dir)

    watch_dir = settings["paths"]["watch_dir"]
    Path(watch_dir).mkdir(parents=True, exist_ok=True)

    print("\n" + "═"*60)
    print("  💳 cc_autopilot — Credit Card Statement Processor")
    print("═"*60)
    print(f"  Watch folder : {watch_dir}")
    print(f"  Ledger       : {settings['paths']['ledger_csv']}")
    print(f"  Report       : {settings['paths']['report_html']}")
    print(f"  Insights out : {settings['paths']['output_dir']}")
    print("═"*60)
    print("  Drop any credit card statement PDF into the watch folder.")
    print("  The report and insights will be regenerated automatically.")
    print("  Press Ctrl+C to stop.\n")

    logger.info("cc_autopilot started")
    logger.info(f"Watch dir: {watch_dir}")

    # Process any PDFs already sitting in the watch folder
    process_existing_pdfs(watch_dir, settings, logger)

    # Start watching
    if WATCHDOG_AVAILABLE:
        handler  = PDFHandler(settings, logger)
        observer = Observer()
        observer.schedule(handler, watch_dir, recursive=False)
        observer.start()
        logger.info(f"Watchdog observer started on {watch_dir}")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
            logger.info("Watcher stopped by user")
        observer.join()
    else:
        logger.warning("watchdog not installed — using polling (10s interval)")
        logger.warning("Install watchdog for instant detection: pip install watchdog")
        poll_folder(watch_dir, settings, logger)


if __name__ == "__main__":
    main()
