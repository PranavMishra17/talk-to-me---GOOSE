from proxy_core.agenda import Agenda, is_bye, is_no, is_yes
from proxy_core.shape import problems


def agenda():
    a = Agenda()
    a.plan("x")
    return a


def test_action_fires_only_on_yes():
    a = agenda()
    assert a.resolve("yes") == []                        # nothing pending: a yes means nothing
    a.ask("take_message", {"message": "m"})
    assert a.resolve("tell him dinner works") == []
    assert a.pending                                     # an unrelated turn leaves it waiting
    assert a.resolve("yes please") == [("take_message", {"message": "m"})]
    assert a.resolve("yes") == []                        # fires once
    assert not a.slots.get("confirmed")                  # the read-back owns confirmed, not this yes


def test_no_and_second_thoughts_do_not_fire():
    a = agenda()
    a.ask("end_call", {})
    assert a.resolve("yes but make it Sunday") == [] and a.pending
    assert a.resolve("no, wait") == [] and not a.pending


def test_correction_replaces_the_pending_action():
    a = agenda()
    a.ask("take_message", {"message": "Saturday"})
    a.ask("take_message", {"message": "Sunday"})
    assert a.resolve("okay") == [("take_message", {"message": "Sunday"})]


def test_yes_and_bye_words():
    assert is_yes("Yeah, go ahead.") and not is_yes("no") and not is_yes("not yet okay")
    assert not is_yes("I'm not sure") and is_yes("No problem, go ahead") and not is_no("No worries")
    assert is_bye("That's all, goodbye.") and not is_bye("Is he around?")


def test_voice_shape():
    assert problems("Tomorrow at 2, or 9 in the morning?") == []
    assert problems("Got it, just to be sure, is that 7 pm or 7 am?") == []
    assert problems("Monday, Tuesday, Wednesday, or Friday?") == ["4 options"]
    assert "list" in problems("Options:\n1. Monday\n2. Tuesday")
    assert problems("One. Two. Three.") == ["3 sentences"]
    assert problems("One. Two. Three.", read_back=True) == []
