"""Table tests for the canonical channel classifier (src/core/channels.py)."""
import pytest

from community.core.channels import channel_kind, is_user_postable


@pytest.mark.parametrize("cid,expected_kind", [
    # user-facing DM
    ("dm-mgr", "dm"),
    ("dm-soeun", "dm"),
    ("dm", "dm"),
    # user-facing group
    ("group-main", "group"),
    ("group-cafe", "group"),
    ("group", "group"),
    # manager / system
    ("mgr-system-log", "mgr"),
    ("mgr-foo", "mgr"),
    ("mgr", "mgr"),
    # internal agent-to-agent
    ("internal-dm-a-b", "internal-dm"),
    ("internal-dm", "internal-dm"),
    ("internal-group-team", "internal-group"),
    ("internal-group", "internal-group"),
    # unknown / arbitrary → permissive group default (e.g. web-chat keys)
    ("webchat-owner", "group"),
    ("random", "group"),
    ("", "group"),
])
def test_channel_kind(cid, expected_kind):
    assert channel_kind(cid) == expected_kind


@pytest.mark.parametrize("cid,postable", [
    ("dm-mgr", True),
    ("group-main", True),
    ("webchat-owner", True),   # unknown → group default → postable
    ("mgr-system-log", False),
    ("mgr", False),
    ("internal-dm-a-b", False),
    ("internal-group-team", False),
])
def test_is_user_postable(cid, postable):
    assert is_user_postable(cid) is postable


def test_internal_not_misclassified_as_dm_or_group():
    # internal-dm-* must NOT be read as a user-facing dm.
    assert channel_kind("internal-dm-x") == "internal-dm"
    assert is_user_postable("internal-dm-x") is False
    # internal-group-* must NOT be read as a user-facing group.
    assert channel_kind("internal-group-x") == "internal-group"
    assert is_user_postable("internal-group-x") is False
