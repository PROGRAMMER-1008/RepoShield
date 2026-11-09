import pytest
from common.money import from_cents, to_cents


def test_to_cents():
    assert to_cents("12.34") == 1234
    assert to_cents(5) == 500
    assert to_cents("0.29") == 29      # float pitfall: 0.29 * 100 == 28.999999999999996


def test_negative_rejected():
    with pytest.raises(ValueError):
        to_cents(-1)


def test_from_cents():
    assert from_cents(1205) == "12.05"
