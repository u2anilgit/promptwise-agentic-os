import pytest
from core.packs.semver import parse_version, satisfies, InvalidVersionError


def test_parse_version_valid():
    assert parse_version("0.4.2") == (0, 4, 2)


def test_parse_version_rejects_garbage():
    with pytest.raises(InvalidVersionError):
        parse_version("not-a-version")


def test_parse_version_rejects_two_part():
    with pytest.raises(InvalidVersionError):
        parse_version("1.2")


def test_satisfies_within_range():
    assert satisfies("0.4.2", ">=0.4.0,<0.5.0") is True


def test_satisfies_below_range():
    assert satisfies("0.3.9", ">=0.4.0,<0.5.0") is False


def test_satisfies_at_upper_bound_is_exclusive():
    assert satisfies("0.5.0", ">=0.4.0,<0.5.0") is False


def test_satisfies_single_clause():
    assert satisfies("1.0.0", ">=1.0.0") is True


def test_satisfies_rejects_malformed_clause():
    with pytest.raises(InvalidVersionError):
        satisfies("1.0.0", "~1.0.0")
