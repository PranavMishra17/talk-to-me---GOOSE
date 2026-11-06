import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # no pytest pythonpath configured

from proxy_core.agenda import Agenda


def make():
    a = Agenda()
    a.plan("book a table")
    return a


def done(a):
    return {i.id for i in a.items if i.done}


def test_out_of_order_completion():
    a = make()
    a.update_slots({"confirmed": True})
    assert done(a) == {"read_back"} and a.focus().id == "identify"
    a.update_slots({"name": "Sam"})
    assert a.focus().id == "learn_ask"


def test_front_loaded_closes_many_in_one_update():
    a = make()
    a.update_slots({"name": "Sam", "topic": "dinner", "details": "7pm", "confirmed": True})
    assert done(a) == {"identify", "learn_ask", "read_back"}
    assert a.focus().id == "close"


def test_contradiction_undoes_dependents():
    a = make()
    a.update_slots({"name": "Sam", "topic": "dinner", "details": "7pm"})
    a.update_slots({"details": "8pm"})
    assert a.slots["details"] == "8pm"
    assert done(a) == {"identify"} and a.focus().id == "learn_ask"


def test_item_and_call_limits():
    a = Agenda(max_turns_per_call=5)
    a.plan("x")
    for _ in range(3):
        assert not a.should_force_advance()
        a.tick()
    assert a.should_force_advance()
    a.force_advance()
    assert a.focus().id == "learn_ask" and not a.exhausted()
    a.tick(); a.tick()
    assert a.exhausted()


def test_render_and_round_trip():
    a = make()
    a.update_slots({"name": "Sam"})
    a.tick()
    block = a.render_prompt_block()
    assert "[>] FOCUS learn_ask" in block and "name=Sam" in block
    b = Agenda.from_dict(a.to_dict())
    assert b.to_dict() == a.to_dict() and b.render_prompt_block() == block
