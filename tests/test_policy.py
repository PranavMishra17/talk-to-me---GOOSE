import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # no pytest pythonpath configured

from proxy_core.policy import get_facts, resolve_tier


def test_contact_tiers():
    assert resolve_tier("pranav", "sam") == "friends"
    assert resolve_tier("pranav", "Rohan") == "family"
    assert resolve_tier("pranav", "lena") == "friends"
    assert resolve_tier("rohan", "lena") == "family"
    assert resolve_tier("pranav", "+15550100333") == "family"


def test_unknown_and_claimed_are_public():
    assert resolve_tier("pranav", "+19998887777") == "public"
    assert resolve_tier("pranav", "I am Rohan") == "public"  # claimed string is not an identity


def test_facts_by_tier():
    assert set(get_facts("pranav", "public")) == {"availability", "city"}
    assert "home_address" not in get_facts("pranav", "friends")
    assert "home_address" in get_facts("pranav", "family")
    assert "phone" not in get_facts("pranav", "family")
    assert "phone" in get_facts("pranav", "private")
    assert get_facts("pranav", "bogus") == get_facts("pranav", "public")


def test_summoned_tier_caps_at_requesters_standing():
    from proxy_core.policy import summoned_tier
    assert summoned_tier("rohan", "+15550100222", "friends", "pranav") == "friends"   # Sam: vouched for by Pranav
    assert summoned_tier("rohan", "+15550100222", "family", "pranav") == "friends"    # Rohan trusts Pranav only so far
    assert summoned_tier("rohan", "", "public", "pranav") == "public"                 # a stranger stays one
    assert summoned_tier("rohan", "+15550100444", "friends", "pranav") == "family"    # Lena is Rohan's own contact
