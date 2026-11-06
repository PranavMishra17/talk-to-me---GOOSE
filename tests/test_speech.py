from datetime import date, datetime, timedelta, timezone

import pytest

from proxy_core.speech import SpeechBuffer, humanize, spoken_day, spoken_phone, spoken_span, spoken_time

FRI = date(2026, 11, 6)
NOW = datetime(2026, 11, 6, 15, 0)


@pytest.mark.parametrize("d, said", [
    (date(2026, 11, 6), "today"), (date(2026, 11, 7), "tomorrow"), (date(2026, 11, 5), "yesterday"),
    (date(2026, 11, 8), "this Sunday"), (date(2026, 11, 9), "next Monday"), (date(2026, 11, 15), "next Sunday"),
    (date(2026, 11, 3), "last Tuesday"), (date(2026, 12, 21), "Monday, December 21st"),
    (date(2027, 1, 2), "Saturday, January 2nd, 2027"),
])
def test_days_are_said_the_way_people_say_them(d, said):
    assert spoken_day(d, FRI) == said


@pytest.mark.parametrize("h, m, said", [
    (14, 0, "2 in the afternoon"), (9, 30, "half past 9 in the morning"), (16, 45, "quarter to 5 in the afternoon"),
    (12, 0, "noon"), (0, 0, "midnight"), (19, 15, "quarter past 7 in the evening"), (10, 40, "10:40 in the morning"),
])
def test_times_have_no_zeros_or_am_pm(h, m, said):
    assert spoken_time(h, m) == said


def test_a_span_names_the_part_of_day_once():
    tz = timezone(timedelta(hours=-5))
    assert spoken_span(datetime(2026, 11, 7, 19, tzinfo=tz), datetime(2026, 11, 7, 21, 30, tzinfo=tz), FRI) == \
        "tomorrow, 7 to half past 9 in the evening"
    assert spoken_span(datetime(2026, 11, 9, 11), datetime(2026, 11, 9, 13), FRI) == \
        "next Monday, 11 in the morning to 1 in the afternoon"


@pytest.mark.parametrize("number, said", [
    ("555-123-4567", "5 5 5, 1 2 3, 4 5 6 7"), ("(617) 555 0199", "6 1 7, 5 5 5, 0 1 9 9"),
    ("+1 617 555 0199", "plus 1, 6 1 7, 5 5 5, 0 1 9 9"), ("5551234", "5 5 5, 1 2 3 4"),
])
def test_phone_numbers_are_digits_in_blocks(number, said):
    assert spoken_phone(number) == said


@pytest.mark.parametrize("text, said", [
    ("He's free 12/21.", "He's free Monday, December 21st."),
    ("How about 11/9 at 2:00 PM?", "How about next Monday at 2 in the afternoon?"),
    ("Booked for 2026-11-07T19:00:00-05:00.", "Booked for tomorrow at 7 in the evening."),
    ("Due 2026-11-12.", "Due next Thursday."),
    ("Meet at 14:00 or 9am", "Meet at 2 in the afternoon or 9 in the morning"),
    ("Call 555.123.4567 back", "Call 5 5 5, 1 2 3, 4 5 6 7 back"),
    ("Around 7:30 then", "Around half past 7 then"),
])
def test_humanize_rewrites_what_tts_reads_badly(text, said):
    assert humanize(text, NOW) == said


@pytest.mark.parametrize("text", ["A table for 2 at the bar.", "It's a 50/50 call.", "That costs $1500000.", "Room 4B, 3 people."])
def test_humanize_leaves_ordinary_numbers_alone(text):
    assert humanize(text, NOW) == text


def test_a_number_split_across_stream_chunks_is_still_read_in_blocks():
    buf = SpeechBuffer(NOW)
    out = "".join(buf.push(c) for c in ["Sure, my number is 555-12", "3-4567. Call me", " 12/", "21."]) + buf.flush()
    assert out == "Sure, my number is 5 5 5, 1 2 3, 4 5 6 7. Call me Monday, December 21st."


def test_the_buffer_lets_finished_clauses_through_at_once():
    buf = SpeechBuffer(NOW)
    assert buf.push("Got it, I'll tell him") == "Got it, "
    assert buf.flush() == "I'll tell him"
