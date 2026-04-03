# Contributing to cc_autopilot

Thank you for your interest in contributing. This document explains how to help.

---

## The most valuable contributions

### 1. Card configuration files

The single highest-impact thing you can do is add a working config YAML for a card that isn't supported yet. Each config covers one card and teaches the system its:
- PDF fingerprints (how to auto-detect this card's statements)
- Reward rate rules (earning rate, zero-earn categories)
- Common vendor mappings specific to that card

**Cards most wanted:**
- SBI SimplyCLICK / SBI Card Elite
- Axis Bank Magnus / Atlas / Flipkart
- ICICI Amazon Pay / Coral / Sapphiro
- American Express MRCC / Gold / Platinum
- Kotak Royale / League
- Yes Bank Marquee / First Preferred
- Any international card (Wise, Revolut, etc.)

**How:**
1. Fork the repo
2. `cp config/_template.yaml config/<bank>_<card>.yaml`
3. Fill in every section — refer to `config/hdfc_infinia.yaml` as a working example
4. Test it: `python cc_processor.py /path/to/real_statement.pdf`
5. Verify the extracted transactions and categories look right
6. Submit a PR

---

## Setting up for development

```bash
git clone https://github.com/yourusername/cc_autopilot.git
cd cc_autopilot

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt

# Copy and configure settings
cp settings.yaml.example settings.yaml
# Fill in your API key and paths
```

---

## Code structure

| File | Responsibility | Modify if... |
|------|---------------|--------------|
| `cc_extractor.py` | PDF → raw transactions via Claude | Statement parsing breaks or needs new formats |
| `cc_categoriser.py` | Categorisation logic (rules + AI) | Category logic needs changing |
| `cc_ledger.py` | CSV management and dedup | Ledger schema changes |
| `cc_insights.py` | Advisory text generation | Insights format or content needs work |
| `cc_report.py` | HTML report generation | Report layout or features |
| `cc_processor.py` | Pipeline orchestration | Adding new pipeline steps |
| `watch_statements.py` | Folder watcher / CLI entry | Watcher behaviour changes |

---

## Guidelines

**Keep PRs focused.** One card config or one feature per PR — easier to review and merge.

**Test with real data.** Before submitting a card config, verify it correctly extracts and categorises at least one real statement. Redact or anonymise the PDF if you include test data.

**Don't commit `settings.yaml`.** It's in `.gitignore` for good reason — it contains your API key.

**Don't commit personal transaction data.** The `data/`, `output/`, and `logs/` directories are gitignored. Keep it that way.

**Match the existing code style.** The codebase is plain Python with docstrings. No type annotation enforcement, but clear variable names and comments are expected.

---

## Reporting issues

Open a GitHub issue with:

- Your card name and bank
- Whether the PDF is text-based or scanned
- The exact error message from the terminal
- (Optional) a snippet of the PDF text showing the transaction table — redact account numbers and personal details

---

## Questions

Open an issue with the `question` label. Happy to help.
