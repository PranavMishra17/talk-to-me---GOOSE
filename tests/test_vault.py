import json

from proxy_core import vault
from proxy_core.policy import TIERS

NAMES = ("gmail", "slack", "notes", "tasks")


def everything(tier):
    return json.dumps([vault._search(n, "", tier, limit=99) for n in NAMES] + [vault.get_calendar(tier)])


def test_no_record_above_the_tier_ever_comes_back():
    for name in NAMES:
        for rank, tier in enumerate(TIERS):
            ids = {r["id"] for r in vault._search(name, "", tier, limit=99)}
            assert ids == {r["id"] for r in vault._load(name) if TIERS.index(r["tier"]) <= rank}
    assert "Northwind" not in everything("family") and "Beacon" not in everything("family")
    assert "Mum" not in everything("friends") and "Oyster" not in everything("public")
    assert "\"tier\":" not in everything("private")


def test_public_calendar_is_free_busy_only():
    assert all(set(e) == {"when", "busy"} for e in vault.get_calendar("public"))
    friend = {e["when"]: e.get("title") for e in vault.get_calendar("friends")}
    assert friend["Sat 7 Nov 09:00 AM to 10:00 AM".replace(" 0", " ")] is None     # cardiology stays a busy block
    assert "Dinner with Sam, Lena and Rohan" in friend.values()


def test_unlabelled_record_counts_as_private(tmp_path):
    (tmp_path / "gmail.json").write_text('[{"id": "x", "date": "", "body": "secret"}, {"id": "y", "date": "", "tier": "bogus"}]')
    assert vault.search_email("", "family", tmp_path) == []
    assert len(vault.search_email("", "private", tmp_path)) == 2


def test_contact_needs_the_number_and_the_owner(tmp_path):
    (tmp_path / "contacts.json").write_text('[{"name": "Sam", "numbers": ["+1 555 222"], "tier": "friends"}]')
    assert vault.find_contact("+1555222", dir=tmp_path)["name"] == "Sam"
    (tmp_path / "contacts.local.json").write_text('[{"name": "Sam", "numbers": ["+1999"], "tier": "family"}]')
    assert vault.find_contact("+1999", dir=tmp_path)["tier"] == "family"
    assert vault.find_contact("+1555222", dir=tmp_path) is None     # the local entry replaced it
    assert vault.find_contact("+1999", owner="rohan", dir=tmp_path) is None
    assert vault.find_contact("Sam", dir=tmp_path) is None and vault.find_contact("", dir=tmp_path) is None


def test_context_is_tier_filtered():
    sam = vault.find_contact("+15550100222")
    text = vault.caller_context(sam, [{"started_at": "2026-11-06T11:42", "summary": "Confirmed dinner"}])
    assert "Sam Okafor" in text and "Confirmed dinner" in text and "Neptune" in text
    lena = vault.caller_context(vault.find_contact("+15550100444"), [])
    assert "7:30" in lena and "gift" not in lena   # her newest friends-tier mail, not the private one above it
