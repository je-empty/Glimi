"""Table tests for the canonical channel classifier (src/core/channels.py)."""
import pytest

from community.core.channels import (
    channel_kind,
    is_owner_dm,
    is_system_channel,
    is_user_postable,
)


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
    # web model: manager channels are owner↔manager DMs → postable
    ("mgr-dashboard", True),
    ("mgr-creator", True),
    # system/log + degenerate + backchannels are NOT postable
    ("mgr-system-log", False),
    ("mgr", False),
    ("internal-dm-a-b", False),
    ("internal-group-team", False),
])
def test_is_user_postable(cid, postable):
    assert is_user_postable(cid) is postable


@pytest.mark.parametrize("cid,system", [
    ("mgr-system-log", True),
    ("mgr", True),
    ("mgr-dashboard", False),
    ("mgr-creator", False),
    ("dm-soeun", False),
    ("group-main", False),
])
def test_is_system_channel(cid, system):
    assert is_system_channel(cid) is system


@pytest.mark.parametrize("cid,owner_dm", [
    # owner↔manager DMs (the Discord "mgr channel" = a web DM)
    ("mgr-dashboard", True),
    ("mgr-creator", True),
    ("dm-soeun", True),
    # not owner DMs
    ("mgr-system-log", False),
    ("group-main", False),
    ("internal-dm-a-b", False),
])
def test_is_owner_dm(cid, owner_dm):
    assert is_owner_dm(cid) is owner_dm


def test_internal_not_misclassified_as_dm_or_group():
    # internal-dm-* must NOT be read as a user-facing dm.
    assert channel_kind("internal-dm-x") == "internal-dm"
    assert is_user_postable("internal-dm-x") is False
    # internal-group-* must NOT be read as a user-facing group.
    assert channel_kind("internal-group-x") == "internal-group"
    assert is_user_postable("internal-group-x") is False
