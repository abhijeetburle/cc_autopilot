# 💳 cc_autopilot

> Drop a credit card statement PDF into a folder. Get a fully interactive financial dashboard + AI-written advisory. Automatically.

![Python](https://img.shields.io/badge/python-3.9%2B-blue?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)
![Powered by Claude](https://img.shields.io/badge/AI-Claude%20Sonnet-orange?style=flat-square)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey?style=flat-square)

---

## What is this?

**cc_autopilot** is a local Python tool that watches a folder on your computer for new credit card statement PDFs. When one arrives, it automatically:

1. **Extracts** every transaction from the PDF (Claude AI handles any layout, any bank)
2. **Categorises** each transaction using your personal vendor history + AI for unknowns
3. **Deduplicates** against your existing transaction history (safe to re-process the same PDF)
4. **Appends** new rows to a local CSV ledger
5. **Writes** an AI-generated advisory — what changed, where you overspent, what to optimise
6. **Regenerates** a self-contained interactive HTML dashboard (`my-cc-report.html`)

No server. No database. No cloud sync. Everything lives in CSVs and a single HTML file on your machine.

---

## Demo

```
$ python watch_statements.py

  💳 cc_autopilot — Credit Card Statement Processor
  ════════════════════════════════════════════════════════
  Watch folder : ~/Documents/cc_statements/incoming
  Report       : ~/Documents/cc_statements/output/my-cc-report.html
  ════════════════════════════════════════════════════════
  Drop any credit card statement PDF into the watch folder.
  Press Ctrl+C to stop.

  🆕 New statement detected: HDFC_Nov_2025.pdf
  Starting pipeline...

  ════════════════════════════════════════════════════════
  ✅ HDFC_Nov_2025.pdf processed successfully
  📊 47 new transactions added
  📝 Insights → output/insights_2025-11_hdfc_infinia.md
  📈 Report   → output/my-cc-report.html
  ════════════════════════════════════════════════════════
```

The report (`my-cc-report.html`) includes 6 interactive panels:

| Panel | What you see |
|---|---|
| **Overview** | Total spend, points earned, reward rate, monthly heatmap, category donut |
| **Year on Year** | Annual spend trend, category mix by year, points vs spend |
| **Month on Month** | Full timeline, seasonal patterns, top months ever, category stack by month |
| **Categories** | Drill-down by category and subcategory, with live filters |
| **Points Analysis** | Best & worst vendors by reward rate, zero-earn spend leak |
| **Transactions** | Full searchable, filterable transaction table |

---

## How it works

```
PDF dropped into watch folder
        │
        ▼
┌──────────────────────────────┐
│  cc_extractor.py             │  pdfplumber extracts raw text
│  + Claude Sonnet             │  AI parses transactions from any layout
└──────────────────────────────┘
        │  raw transactions
        ▼
┌──────────────────────────────┐
│  cc_categoriser.py           │  1. Hard-coded vendor rules  (config YAML)
│                              │  2. Your vendor history      (CSV lookup)
│  + Claude Sonnet             │  3. AI for unknown vendors   (batch call)
└──────────────────────────────┘
        │  categorised + enriched
        ▼
┌──────────────────────────────┐
│  cc_ledger.py                │  Deduplicate → append to transactions_master.csv
│                              │  Update category_vendor_master.csv
└──────────────────────────────┘
        │  updated ledger
        ▼
┌──────────────────────────────┐
│  cc_insights.py              │  Claude writes the statement advisory (.md)
└──────────────────────────────┘
        │
        ▼
┌──────────────────────────────┐
│  cc_report.py                │  Rebuild my-cc-report.html from scratch
└──────────────────────────────┘
```

---

## Supported cards

Any credit card with a **text-based PDF statement** (not scanned/image). The system auto-detects the card from PDF content and loads the matching config.

| Card | Config file | Status |
|------|------------|--------|
| HDFC Bank Infinia | `config/hdfc_infinia.yaml` | ✅ Included |
| ICICI Amazon Pay | `config/icici_amazon_pay.yaml` | ✅ Included |
| Any other card | `config/_template.yaml` | ⚙️ Copy & configure |

Adding support for a new card takes ~10 minutes — copy the template, add your PDF fingerprints and reward rules.

---

## Requirements

- Python 3.9+
- An [Anthropic API key](https://console.anthropic.com/) (~$0.10–0.30 per statement)
- Credit card PDFs with a text layer (downloaded from your bank's portal, not photographed)

---

## Installation

### Step 1 — Clone the repo

```bash
git clone https://github.com/yourusername/cc_autopilot.git
cd cc_autopilot
```

### Step 2 — Create a virtual environment (strongly recommended)

```bash
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows
```

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

**If `pip` isn't in your PATH (common on macOS):**

```bash
python3 -m pip install -r requirements.txt
# or with Homebrew Python:
pip3 install -r requirements.txt
```

---

## Setup

### 1. Get an Anthropic API key

Sign up at [console.anthropic.com](https://console.anthropic.com/) → API Keys → Create key.

Your key looks like: `sk-ant-api03-...`

> **Cost:** A typical monthly statement costs ~₹8–25 ($0.10–0.30 USD) to process.  
> Anthropic does not use API data for training by default.

### 2. Configure settings.yaml

```bash
cp settings.yaml.example settings.yaml
```

Edit `settings.yaml` with your paths and API key:

```yaml
api_key: "sk-ant-your-key-here"

paths:
  watch_dir:         "~/Documents/cc_statements/incoming"
  ledger_csv:        "~/Documents/cc_statements/data/transactions_master.csv"
  vendor_master_csv: "~/Documents/cc_statements/data/category_vendor_master.csv"
  output_dir:        "~/Documents/cc_statements/output"
  report_html:       "~/Documents/cc_statements/output/my-cc-report.html"
  log_dir:           "~/Documents/cc_statements/logs"
  processed_log:     "~/Documents/cc_statements/data/processed_pdfs.txt"
```

All folders are created automatically on first run.

### 3. Start the watcher

```bash
python watch_statements.py
```

Leave it running. Drop a statement PDF into `watch_dir`. Done.

---

## Adding a new card / bank

1. Copy the template:

```bash
cp config/_template.yaml config/axis_atlas.yaml
```

2. Open your new file and fill in the required fields:

```yaml
card:
  id: axis_atlas
  name: Axis Bank Atlas Credit Card
  bank: Axis Bank
  network: Visa

# Strings that uniquely identify this card's statement PDF
pdf_fingerprints:
  - "Atlas Credit Card"
  - "Axis Bank"

# Reward rate rules
rewards:
  standard_rate: 5.0    # 5 EDGE miles per ₹100 spent
  standard_per:  100
  zero_earn_categories:
    - Taxes & Government
  zero_earn_keywords:
    - FUEL
    - PETROL

# Hard-coded vendor mappings (keyword → category)
vendor_rules:
  "ZOMATO":   [Food & Dining, Delivery, true]
  "SWIGGY":   [Food & Dining, Delivery, true]
  "UBER":     [Travel, Cab & Local Transport, true]
  "CBDT":     [Taxes & Government, Income Tax, false]
  # add more...
```

3. Drop a statement from that card — the system detects it automatically.

---

## Processing a single PDF manually

Without the watcher, process one PDF directly:

```bash
python cc_processor.py /path/to/statement.pdf
```

With a custom settings file:

```bash
python cc_processor.py /path/to/statement.pdf /path/to/settings.yaml
```

---

## File structure

```
cc_autopilot/
├── watch_statements.py        ← Entry point — run this
├── cc_processor.py            ← Pipeline orchestrator
├── cc_extractor.py            ← PDF extraction + Claude transaction parser
├── cc_categoriser.py          ← Rule-based + AI categorisation
├── cc_ledger.py               ← CSV ledger + deduplication
├── cc_insights.py             ← Claude statement advisory
├── cc_report.py               ← Interactive HTML report
│
├── settings.yaml              ← Your config (gitignored — never commit this)
├── settings.yaml.example      ← Template — copy to settings.yaml
├── requirements.txt
│
├── config/
│   ├── hdfc_infinia.yaml      ← HDFC Infinia — ready to use
│   └── _template.yaml         ← Template for new cards
│
└── README.md
```

---

## Category taxonomy

| Category | Subcategories |
|---|---|
| Food & Dining | Dine Out, Delivery, Liquor, Groceries |
| Shopping | Online & General, Apparels, Electronics, Home & Furniture, Vouchers |
| Travel | Flights & Trains, Accommodation, Cab, Tolls, Forex & Fees |
| Health & Wellness | Medical & Hospital, Beauty & Grooming, Pharmacy |
| Education | School & Tuition, Online Courses |
| Investments & Assets | Real Estate, Insurance, NPS & Pension |
| Taxes & Government | Income Tax, Property Tax, Government Services |
| Utilities & Bills | Streaming & OTT, Internet, Mobile, Electricity |
| Vehicle & Mobility | Fuel, Service & Maintenance |
| Entertainment | Movies & Events |
| Professional & Fees | Subscriptions, Bank Fees |
| Transfers & Payments | CC Bill Payment, Cashback & Reversals |

Fully customisable per card in `config/<card>.yaml`.

---

## Compatibility

| Scenario | Result |
|---|---|
| Same card, different months | ✅ Works — deduplicated automatically |
| Same card, layout changed slightly | ✅ Works — Claude handles layout variations |
| Multiple cards from same bank | ⚠️ Add a separate config YAML per card |
| Different bank entirely | ⚠️ Add a config YAML with that bank's PDF fingerprints |
| Multiple cards in one ledger | ✅ Works — card auto-detected per PDF |
| Scanned / image-only PDF | ❌ Not supported — needs OCR pre-processing |

---

## Privacy & security

- **All your data is local** — CSVs and HTML on your machine only
- **API calls** are made only during processing (no background data collection)
- **Anthropic's API privacy policy:** [anthropic.com/privacy](https://www.anthropic.com/privacy) — API data not used for training by default
- **The HTML report is offline** — no tracking, no analytics
- **Never commit `settings.yaml`** — it contains your API key. It is listed in `.gitignore` by default.
- **No-AI mode:** set `api_key: ""` to skip all Claude calls. Unknown vendors categorise as `Others / Others`.

---

## Troubleshooting

**`zsh: command not found: pip`**
```bash
python3 -m pip install -r requirements.txt
```

**`No text extracted from PDF — may be scanned`**  
Download the statement directly from your bank's internet banking portal as a PDF. Do not use a photographed or printed-then-scanned version.

**`No card config matched — falling back to first config`**  
Add a YAML config for your card. Copy `config/_template.yaml` and add the unique strings from your statement PDF header as `pdf_fingerprints`.

**`API key invalid / authentication error`**  
Ensure your key in `settings.yaml` starts with `sk-ant-` and has no extra spaces or quotes inside the value.

**Watcher not detecting new PDFs instantly**  
Install `watchdog` for instant file detection. Without it, the system falls back to 10-second polling:
```bash
pip install watchdog
```

**Duplicate transactions after re-processing**  
The dedup key is `(date, first-30-chars-of-description, amount)`. Safe to re-process the same PDF — duplicates are skipped. If near-duplicates slip through due to description changes, remove them manually from the CSV.

---

## Contributing

Contributions are welcome — especially config YAMLs for new banks and cards.

### Adding a card config (most needed)

1. Fork the repo
2. Copy `config/_template.yaml` → `config/<bank>_<card>.yaml`
3. Fill in all sections and test with a real statement
4. Submit a PR with the card name and bank in the description

### Code contributions

```bash
git clone https://github.com/yourusername/cc_autopilot.git
cd cc_autopilot
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Make changes, test
python cc_processor.py /path/to/test_statement.pdf

# Submit a focused PR — one feature or one config per PR
```

### Reporting issues

Open a GitHub issue with:
- Card name and bank
- Whether it's a text PDF or scanned image
- Error message or unexpected behaviour
- (Optional) a redacted snippet of the PDF text showing the transaction table format

---

## Roadmap

- [ ] Config YAMLs for popular cards (SBI SimplyCLICK, Axis Magnus, ICICI Coral, Amex MRCC, Flipkart Axis)
- [ ] `--backfill` mode: process an entire folder of historical PDFs in chronological order
- [ ] Optional OCR support for scanned PDFs (`pytesseract`)
- [ ] Desktop notification when processing completes
- [ ] Auto-open report in browser after processing

---

## License

[MIT](LICENSE) — use it, fork it, build on it.

---

## Acknowledgements

Built with:
- [Claude](https://www.anthropic.com/) (Anthropic) — transaction extraction, categorisation, insights generation
- [pdfplumber](https://github.com/jsvine/pdfplumber) — PDF text layer extraction
- [Chart.js](https://www.chartjs.org/) — interactive dashboard charts
- [watchdog](https://github.com/gorakhargosh/watchdog) — filesystem event watching

---

*If this saves you time or helps you understand your spending better, a ⭐ on GitHub is appreciated.*
