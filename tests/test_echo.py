from proxy_core.echo import EchoGuard


def test_leaked_tts_line_is_dropped_while_playing_and_just_after():
    g = EchoGuard()
    g.said("He is free after six on Saturday evening")
    assert g.is_echo("free after six on Saturday", 0)
    g.ended(10)
    assert g.is_echo("he is free after six", 12)


def test_echo_expires_and_real_speech_passes():
    g = EchoGuard()
    g.said("He is free after six on Saturday evening")
    g.ended(10)
    assert not g.is_echo("he is free after six", 14)
    assert not g.is_echo("yes Saturday works", 11)              # too short to call
    assert not g.is_echo("could you book us a table instead", 11)


def test_other_agents_speech_counts():
    g = EchoGuard()
    g.heard("Rohan is busy until five on Saturday", 5)
    assert g.is_echo("Rohan is busy until five", 6)
