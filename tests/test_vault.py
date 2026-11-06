import json
from datetime import date

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
    assert "15 percent" not in everything("family") and "Beacon" not in everything("family")
    assert "Mum" not in everything("friends") and "Oyster" not in everything("public")
    assert "\"tier\":" not in everything("private")


def test_profile_stops_at_the_tier():
    assert set(vault.get_profile("public")) == {"name", "role", "city", "work", "best_time_to_reach"}
    assert "coffee" in vault.get_profile("friends") and "family_routine" not in vault.get_profile("friends")
    assert "health" in vault.get_profile("private") and "health" not in vault.get_profile("family")


def test_public_calendar_is_free_busy_only():
    assert all(set(e) == {"when", "busy"} for e in vault.get_calendar("public"))
    friend = {e["when"]: e.get("title") for e in vault.get_calendar("friends")}
    assert friend["Sat 7 Nov 09:00 AM to 10:00 AM".replace(" 0", " ")] is None     # cardiology stays a busy block
    assert "Dinner with Sam, Lena and Rohan" in friend.values()


def test_unlabelled_record_counts_as_private(tmp_path):
    (tmp_path / "gmail.json").write_text('[{"id": "x", "date": "", "body": "secret"}, {"id": "y", "date": "", "tier": "bogus"}]')
    assert vault.search_email("", "family", tmp_path) == []
    assert len(vault.search_email("", "private", tmp_path)) == 2


def test_a_bad_local_file_never_takes_a_call_down(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOSE_CONTACTS_LOCAL", raising=False)
    (tmp_path / "contacts.json").write_text('[{"name": "Sam", "numbers": ["+1555"], "tier": "friends"}]')
    (tmp_path / "contacts.local.json").write_text('{"contacts": [{"name": "half')
    assert vault.find_contact("+1555", dir=tmp_path)["name"] == "Sam"
    (tmp_path / "contacts.local.json").write_text('{"contacts": [{"name": "X", "numbers": ["+1"], "tier": "boss"}, {"numbers": ["+2"]}, 7]}')
    assert vault.find_contact("+1", dir=tmp_path)["tier"] == "public" and vault.find_contact("+2", dir=tmp_path) is None


def test_private_never_reaches_the_phone():
    assert vault.phone_tier("private") == "family" and vault.phone_tier("friends") == "friends"


def test_contact_needs_the_number_and_the_owner(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOSE_CONTACTS_LOCAL", raising=False)
    (tmp_path / "contacts.json").write_text('[{"name": "Sam", "numbers": ["+1 555 222"], "tier": "friends"}]')
    assert vault.find_contact("+1555222", dir=tmp_path)["name"] == "Sam"
    (tmp_path / "contacts.local.json").write_text('[{"name": "Sam", "numbers": ["+1999"], "tier": "family"}]')
    assert vault.find_contact("+1999", dir=tmp_path)["tier"] == "family"
    assert vault.find_contact("+1555222", dir=tmp_path) is None     # the local entry replaced it
    assert vault.find_contact("+1999", owner="rohan", dir=tmp_path) is None
    assert vault.find_contact("Sam", dir=tmp_path) is None and vault.find_contact("", dir=tmp_path) is None


TODAY = date(2026, 11, 6)


def bundle(number):
    return vault.prefetch("pranav", vault.find_contact(number), [], TODAY)


def test_prefetch_is_tier_filtered_and_relevant():
    lena = bundle("+15550100444")
    assert "7:30" in lena and "gift" not in lena     # her friends-tier mail, not the private one
    sam = bundle("+15550100222")
    assert "Neptune" in sam and "Northwind" not in sam and "Cardiology" not in sam and "busy" in sam
    priya = bundle("+15550100666")
    assert "liability cap" in priya and "Neptune" not in priya and "Dinner" not in priya  # work, not the owner's evenings
    assert "15 percent" not in priya and "12 percent" not in priya   # private stays private, work or not
    assert "18,240" not in vault.prefetch("pranav", {"name": "Beacon Bank", "relationship": "owner", "tier": "private"}, [], TODAY)


def test_prefetch_stays_short_and_only_for_the_owner():
    for number in ("+15550100222", "+15550100333", "+15550100444", "+15550100555", "+15550100666"):
        assert 0 < len(bundle(number).split()) <= vault.PREFETCH_WORDS
    assert vault.prefetch("rohan", vault.find_contact("+15550100222"), [], TODAY) == ""
