"""Safety invariants of the two demo setups: what the model can be handed, per owner and tier. No network."""
import asyncio
import json
from datetime import date

from app.agent import GooseAgent
from proxy_core import policy, vault

MUHAMMAD = "+15550100555"
TODAY = date(2026, 11, 6)
PRIVATE = ("640", "debts", "audit", "Bristol", "Four Seasons")


def everything(tier, owner):
    home = vault.owner_dir(owner)
    rows = [vault.get_profile(tier, home), vault.get_calendar(tier, home), policy.get_facts(owner, tier)]
    for read in (vault.search_email, vault.search_slack, vault.search_notes):
        rows.append(read("", tier, home))
        rows.append(read("price floor car wash reasons location dinner", tier, home))
    return json.dumps(rows)


def test_nothing_private_reaches_any_phone_tier():
    for tier in ("public", "friends", "family"):
        for owner in ("pranav", "skyler"):
            blob = everything(tier, owner)
            assert not any(p in blob for p in PRIVATE), (tier, owner)


def test_muhammad_bundle_has_the_pr_but_not_the_incident():
    c = vault.find_contact(MUHAMMAD)
    assert c["relationship"] == "colleague" and vault.phone_tier(c["tier"]) == "friends"
    bundle = vault.prefetch("pranav", c, [], TODAY)
    assert "482" in bundle and "Pranav's approval" in bundle
    assert not any(w in bundle.lower() for w in ("streaming", "inc-219", "bristol"))
    assert "Monday" in json.dumps(vault.search_slack("streaming issue", "friends"))     # the tool does find it


def test_stranger_sees_neither_work_item():
    assert vault.search_slack("PR 482", "public") == [] and vault.search_slack("streaming", "public") == []
    assert vault.search_email("streaming", "public") == []


def test_owners_do_not_share_data():
    jesse = GooseAgent("jesse", caller="+15550100222")      # Sam, a friend of Pranav, is a stranger here
    assert jesse.contact is None and jesse.caller_tier == "public" and "Pranav" not in jesse._prompt()
    assert "Maya" not in jesse._prompt() and "Goose" not in jesse._prompt()
    assert "A1 Car Wash" in json.dumps(jesse._rows(vault.get_profile))
    assert "Honk" not in jesse._rows(vault.get_profile)
    assert asyncio.run(jesse.get_facts("Pranav")) == {} and asyncio.run(jesse.get_facts("Rohan")) == {}
    assert asyncio.run(jesse.get_facts("Skyler"))["sale"]
    assert vault.find_contact("+15550100777", "skyler")["name"] == "Marie Schrader"
    assert vault.find_contact("+15550100777") is None       # and Skyler's contact is nobody on Pranav's side
    assert "Skyler" not in GooseAgent("goose", caller="").instructions


def test_real_numbers_stay_with_pranav(monkeypatch, tmp_path):
    local = tmp_path / "local.json"
    local.write_text(json.dumps([{"name": "Real", "numbers": ["+19998887777"], "tier": "family"}]))
    monkeypatch.setenv("GOOSE_CONTACTS_LOCAL", str(local))
    assert vault.find_contact("+19998887777")["name"] == "Real"
    assert vault.find_contact("+19998887777", "skyler") is None


def test_skyler_is_in_her_book_and_pranav_is_a_stranger_there(tmp_path, monkeypatch):
    assert vault.find_contact("+11111111", "skyler")["relationship"] == "owner"
    local = tmp_path / "local.json"
    local.write_text('{"contacts": [{"name": "Pranav", "relationship": "owner", "tier": "private", "numbers": ["+15550100111"]}]}')
    monkeypatch.setenv("GOOSE_CONTACTS_LOCAL", str(local))
    assert vault.find_contact("+15550100111", "pranav")["relationship"] == "owner"
    assert vault.find_contact("+15550100111", "skyler") is None
    assert "Pranav" not in [c["name"] for c in vault.contacts(vault.owner_dir("skyler"))]
    assert vault.number_for("Pranav", "skyler") is None
