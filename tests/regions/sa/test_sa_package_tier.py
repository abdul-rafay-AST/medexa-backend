"""Package tier resolution tests."""

from __future__ import annotations

import pytest

from medexa.regions.sa.billing.package_tier import is_package_code, resolve_package_tier


@pytest.mark.parametrize(
    "code,minutes,expected",
    [
        ("98014-00-10", 10, "98014-00-10"),
        ("98014-00-10", 20, "98014-00-20"),
        ("98014-00-10", 45, "98014-00-30"),
        ("98014-00-10", 55, "98014-00-40"),
        ("98014-00-10", 100, "98014-00-50"),
        ("98010-00-10", 200, "98010-00-60"),
        ("98010-00-10", 250, "98010-00-70"),
        ("98016-00-10", 150, "98016-00-50"),
        ("98016-00-10", 300, "98016-00-50"),
    ],
)
def test_resolve_package_tier(code, minutes, expected):
    assert resolve_package_tier(code, minutes) == expected


def test_non_package_code_unchanged():
    assert resolve_package_tier("11306-00-30", 45) == "11306-00-30"


@pytest.mark.parametrize(
    "code,expected",
    [
        ("98014-00-30", True),
        ("98010-00-10", True),
        ("98016-00-50", True),
        ("11306-00-30", False),
        ("97110", False),
    ],
)
def test_is_package_code(code, expected):
    assert is_package_code(code) is expected
