import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from proxy_core.personality import knob, list_packs, load_pack, nudge_text, render_style

NAMES = ["default", "goose", "jarvis", "jesse"]


def test_all_load():
    assert list_packs() == NAMES
    assert [load_pack(n)["name"] for n in NAMES] == NAMES


@pytest.mark.parametrize("name", NAMES)
def test_render_style(name):
    pack, out = load_pack(name), render_style(load_pack(name))
    assert len(out.split()) <= 100
    for k, v in pack["knobs"].items():
        assert k not in out
        for item in v if isinstance(v, list) else [v]:
            assert str(item) not in out
    assert "I don't have that, I'll ask him" in out and "complete answer" in out
    assert "apologetic" in out and "privacy filter is unaffected" in out


def test_unknown_pack():
    with pytest.raises(ValueError):
        load_pack("nope")


def test_nudge_differs_and_knob():
    for step in range(3):
        assert len({nudge_text(load_pack(n), step) for n in NAMES}) == 3
    assert knob(load_pack("jesse"), "patience_turns") == 2
