"""
Phone normalization is critical — a mismatch means returning runners get re-onboarded.
Tests cover every format we expect to receive from WhatsApp / the test UI.
"""
import pytest
from utils.helpers import normalize_phone
from integrations.sheets import _normalize_phone as sheets_normalize


@pytest.mark.parametrize("input_phone,expected", [
    # Bare 10-digit Indian mobile
    ("9876543210",    "+919876543210"),
    ("9777199410",    "+919777199410"),
    # With country code prefix
    ("+919876543210", "+919876543210"),
    ("919876543210",  "+919876543210"),
    # With leading zero (landline style)
    ("09876543210",   "+919876543210"),
    # Already correct
    ("+14155552671",  "+14155552671"),
    # Spaces and dashes stripped
    ("+91 98765 43210",  "+919876543210"),
    ("98765-43210",      "+919876543210"),
])
def test_normalize_phone_helpers(input_phone, expected):
    assert normalize_phone(input_phone) == expected


@pytest.mark.parametrize("input_phone,expected", [
    ("9876543210",    "+919876543210"),
    ("+919876543210", "+919876543210"),
    ("919876543210",  "+919876543210"),
])
def test_normalize_phone_sheets(input_phone, expected):
    """sheets._normalize_phone must match utils.helpers.normalize_phone."""
    assert sheets_normalize(input_phone) == expected


def test_both_normalizers_agree():
    """Both normalizers must produce identical output — they're used for lookup matching."""
    phones = ["9876543210", "+919876543210", "919876543210", "09876543210"]
    for p in phones:
        assert normalize_phone(p) == sheets_normalize(p), f"Mismatch for {p}"


def test_normalized_phones_match_each_other():
    """Bare, +91, and 91-prefix versions of the same number must all normalize to the same value."""
    bare   = normalize_phone("9876543210")
    with91 = normalize_phone("+919876543210")
    no_plus = normalize_phone("919876543210")
    assert bare == with91 == no_plus
