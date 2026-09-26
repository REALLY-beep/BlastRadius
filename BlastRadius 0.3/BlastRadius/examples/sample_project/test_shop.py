"""
Existing tests – intentionally incomplete.
They only test the happy path of calculate_total.
"""

from shop import calculate_total


def test_calculate_total_basic():
    assert calculate_total([10, 20, 30]) == 60


def test_calculate_total_empty():
    assert calculate_total([]) == 0