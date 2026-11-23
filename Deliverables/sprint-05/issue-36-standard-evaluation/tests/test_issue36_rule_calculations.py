
import pytest


def calculate_normal_depth(height):
    return max(0.4 * height, 3)


def calculate_commercial_depth(height):
    return max(0.2 * height, 3)


@pytest.mark.parametrize(
    "height, expected",
    [
        (10, 4),
        (5, 3),
        (20, 8),
        (2, 3),
    ],
)
def test_normal_setback_formula(height, expected):
    assert calculate_normal_depth(height) == expected


@pytest.mark.parametrize(
    "height, expected",
    [
        (10, 3),
        (20, 4),
        (5, 3),
        (30, 6),
    ],
)
def test_commercial_setback_formula(height, expected):
    assert calculate_commercial_depth(height) == expected


def test_normal_and_commercial_rules_are_different():
    height = 20

    assert calculate_normal_depth(height) == 8
    assert calculate_commercial_depth(height) == 4
