"""Tier policy: who may see which persona facts. Raw persona dicts never leave this module."""
import yaml
from proxy_core.config import ROOT

TIERS = ["public", "friends", "family", "private"]


def load_personas(path=ROOT / "personas.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _rank(tier: str) -> int:
    return TIERS.index(tier) if tier in TIERS else 0  # unknown tier string => public


def get_facts(person: str, caller_tier: str, personas: dict | None = None) -> dict:
    """key -> value for facts at or below caller_tier (fresh dict, not the raw persona)."""
    p = (personas or load_personas()).get(person.strip().lower(), {})  # the model says "Pranav"; keys are lowercase
    return {f["key"]: f["value"] for f in p.get("facts", []) if _rank(f["tier"]) <= _rank(caller_tier)}


def resolve_tier(person: str, identity: str, personas: dict | None = None) -> str:
    """Tier from a VERIFIED contact name or caller number only.
    A caller's *claimed* identity ("I am Rohan") must never be passed here: it never raises tier."""
    ident = (identity or "").strip().lower()
    for name, c in (personas or load_personas()).get(person, {}).get("contacts", {}).items():
        if ident == name.lower() or ident in c.get("numbers", []):
            return c["tier"] if c["tier"] in TIERS else "public"
    return "public"
