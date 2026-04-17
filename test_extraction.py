#!/usr/bin/env python3
"""
test_extraction.py
------------------
Unit tests for the local PDF extraction functionality.
Run with: python test_extraction.py
"""

import sys
from pathlib import Path

# Add cc_autopilot to path
sys.path.insert(0, str(Path(__file__).parent))

from cc_extractor import (
    extract_pdf_text,
    extract_transactions,
    detect_card_config,
    parse_transaction_row,
    split_transaction_rows,
    find_transaction_section,
    is_noise_line,
    normalize_whitespace,
    build_date_regex,
    parse_date_string,
    parse_amount,
)
import yaml


def load_test_configs():
    """Load test configs from config/ directory."""
    config_dir = Path('config')
    configs = {}
    for p in config_dir.glob('*.yaml'):
        if p.name.startswith('_'):
            continue
        with open(p, 'r', encoding='utf-8') as f:
            configs[p.stem] = yaml.safe_load(f)
    return configs


def test_normalize_whitespace():
    """Test whitespace normalization."""
    assert normalize_whitespace("  a  b  \n c  ") == "a b \n c"
    assert normalize_whitespace("a\tb") == "a b"
    print("✓ normalize_whitespace")


def test_build_date_regex():
    """Test date regex building."""
    config = {"parsing": {"date_format": "%d/%m/%Y"}}
    regex = build_date_regex(config)
    assert regex == r"\d{1,2}/\d{1,2}/\d{4}"
    print("✓ build_date_regex")


def test_parse_amount():
    """Test amount parsing."""
    assert parse_amount("1,234.56") == 1234.56
    assert parse_amount("1,000.00") == 1000.0
    assert parse_amount("500") == 500.0
    print("✓ parse_amount")


def test_parse_date_string():
    """Test date parsing."""
    date = parse_date_string("12/12/2025", "%d/%m/%Y")
    assert date == "12/12/2025"
    print("✓ parse_date_string")


def test_is_noise_line():
    """Test noise line detection."""
    config = {"parsing": {}}
    assert is_noise_line("Page 1 of 5", config)
    assert is_noise_line("TRANSACTION DESCRIPTION", config)
    assert not is_noise_line("AMAZON PAYMENT 100.00", config)
    print("✓ is_noise_line")


def test_extract_pdf_text():
    """Test PDF text extraction."""
    text = extract_pdf_text('config/samplepdf/CCXX45_11-01-2026.pdf')
    assert len(text) > 1000  # Should have substantial text
    assert 'HDFC' in text.upper()
    print("✓ extract_pdf_text")


def test_detect_card_config():
    """Test card config detection."""
    configs = load_test_configs()
    text = extract_pdf_text('config/samplepdf/CCXX45_11-01-2026.pdf')
    config = detect_card_config(text, configs)
    assert config['card']['id'] == 'hdfc_infinia'
    print("✓ detect_card_config (HDFC)")

    text = extract_pdf_text('config/samplepdf/ICICI_CCXX08_05-03-2026.pdf')
    config = detect_card_config(text, configs)
    assert config['card']['id'] == 'icici_amazon_pay'
    print("✓ detect_card_config (ICICI)")


def test_extract_transactions():
    """Test full transaction extraction."""
    configs = load_test_configs()

    # Test HDFC
    text = extract_pdf_text('config/samplepdf/CCXX45_11-01-2026.pdf')
    config = detect_card_config(text, configs)
    txns = extract_transactions(text, config, 'test.pdf')
    assert len(txns) >= 40  # Should extract many transactions
    # Check first transaction
    txn = txns[0]
    assert 'date' in txn
    assert 'description' in txn
    assert 'amount' in txn
    assert 'is_credit' in txn
    assert 'ACC HOSPITALITY' in txn['description'].upper()
    print("✓ extract_transactions (HDFC)")

    # Test ICICI
    text = extract_pdf_text('config/samplepdf/ICICI_CCXX08_05-03-2026.pdf')
    config = detect_card_config(text, configs)
    txns = extract_transactions(text, config, 'test.pdf')
    assert len(txns) >= 2
    txn = txns[0]
    assert 'AMAZON PAY' in txn['description'].upper() or 'Autodebit' in txn['description']
    print("✓ extract_transactions (ICICI)")


def run_tests():
    """Run all tests."""
    print("Running extraction tests...\n")

    try:
        test_normalize_whitespace()
        test_build_date_regex()
        test_parse_amount()
        test_parse_date_string()
        test_is_noise_line()
        test_extract_pdf_text()
        test_detect_card_config()
        test_extract_transactions()

        print("\n✅ All tests passed!")
        return True

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)