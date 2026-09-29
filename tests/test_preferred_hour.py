"""
get_preferred_hour must keep 0 (midnight) as a real choice.

The settings dropdown offers "00:00 (Midnight)" with value 0, and -1 means "any time". A
truthiness test turned a stored 0 into -1, so choosing midnight behaved like "any time".
"""
import pytest

from app.dependencies import get_preferred_hour


class _Cursor:
    def __init__(self, row):
        self.row = row

    def execute(self, sql, params=None):
        pass

    def fetchone(self):
        return self.row


@pytest.mark.parametrize("stored, expected", [
    (0, 0),
    (8, 8),
    (23, 23),
    (-1, -1),
    (None, -1),
])
def test_stored_hour_is_returned(stored, expected):
    assert get_preferred_hour(_Cursor({"preferred_hour": stored}), "some-uuid") == expected


def test_missing_profile_row_means_any_time():
    assert get_preferred_hour(_Cursor(None), "some-uuid") == -1


def test_no_user_means_any_time():
    assert get_preferred_hour(_Cursor({"preferred_hour": 8}), None) == -1
