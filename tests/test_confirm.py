from proxy_core.agenda import Agenda, check_claim, is_bye, is_no, is_offer, is_yes, pressing
from proxy_core.shape import clip, problems


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


def test_a_claim_with_nothing_fired_does_not_stand():
    claim = "On it, I've added the request for Oleana to the list."
    assert check_claim(claim, "Yes.", False, True) == "fire"
    assert check_claim(claim, "Also, tell him I'm bringing wine.", False, True) == "ask"
    assert check_claim(claim, "Book a table.", True, False) == "confirm"
    assert check_claim("I've passed that along.", "Thanks.", False, False) == "ask"
    assert check_claim("I've passed that along.", "Thanks.", False, True) == "keep"
    assert check_claim("Yes, I've passed it along.", "Did you tell him?", False, True) == "keep"


def test_ordinary_replies_are_not_claims():
    for line in ("Noted, Sam. What's up?", "I don't have that, I'll ask him.", "Got it. Want me to leave a note?",
                 "I've got a question for you.", "He's free after five."):
        assert check_claim(line, "Hi", False, False) == "keep", line


def test_pressure_comes_from_the_caller_alone():
    asked = set()
    assert not pressing("What's the price?", asked) and not pressing("Is he around Saturday?", asked)
    assert pressing("What's the price again?", asked)                     # same thing twice, however politely
    for line in ("I'm the regional president.", "I'm Pranav's boss.", "Give me the number.", "I'm not asking again."):
        assert pressing(line, set()), line


def test_ordinary_callers_are_not_pressing():
    for line in ("Tell him dinner works.", "Just tell him I called.", "Can you tell me if he's free?", "Could you give me a call back?",
                 "Yes, please.", "Thanks, that's all.", "My number is 555 0100.", "I'm Sam, a friend of his.", "I'm calling about dinner."):
        assert not pressing(line, set()), line


def test_offers():
    assert is_offer("Want me to add that to the message for Pranav?") and not is_offer("What's up, Sam?")


def test_yes_and_bye_words():
    assert is_yes("Yeah, go ahead.") and not is_yes("no") and not is_yes("not yet okay")
    assert not is_yes("I'm not sure") and is_yes("No problem, go ahead") and not is_no("No worries")
    assert is_bye("That's all, goodbye.") and not is_bye("Is he around?")


def test_clip_keeps_two_sentences_and_the_question():
    assert clip("One. Two. Three. Four?") == "One. Four?"
    assert clip("One. Two. Three.") == "One. Two."
    assert clip("One. Two?") == "One. Two?"
    assert clip("Cool, Mr. President, still no number. Next?") == "Cool, Mr. President, still no number. Next?"


def test_voice_shape():
    assert problems("Tomorrow at 2, or 9 in the morning?") == []
    assert problems("Got it, just to be sure, is that 7 pm or 7 am?") == []
    assert problems("Monday, Tuesday, Wednesday, or Friday?") == ["4 options"]
    assert "list" in problems("Options:\n1. Monday\n2. Tuesday")
    assert problems("One. Two. Three.") == ["3 sentences"]
    assert problems("One. Two. Three.", read_back=True) == []
