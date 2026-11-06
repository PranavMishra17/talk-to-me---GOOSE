"""The real agent, gate and tools against a scripted model: no network, no credits.
The confirm gate is the judged safety rule: nothing fires without a yes, and nothing is claimed that did not fire."""
import asyncio
import uuid

from livekit.agents import AgentSession, APIConnectOptions, llm

from app.agent import GooseAgent
from proxy_core.config import load_config


class Stream(llm.LLMStream):
    def __init__(self, model, step, **kw):
        super().__init__(model, **kw)
        self.step = step

    async def _run(self):
        call = isinstance(self.step, tuple)
        delta = llm.ChoiceDelta(role="assistant", content=None if call else self.step, tool_calls=[llm.FunctionToolCall(
            name=self.step[0], arguments=self.step[1], call_id=uuid.uuid4().hex)] if call else [])
        self._event_ch.send_nowait(llm.ChatChunk(id=uuid.uuid4().hex, delta=delta))


class Script(llm.LLM):
    def __init__(self, steps):
        super().__init__()
        self.steps = list(steps)

    def chat(self, *, chat_ctx, tools=None, conn_options=APIConnectOptions(), **kw):
        return Stream(self, self.steps.pop(0) if self.steps else "Okay.", chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


def play(turns):
    """turns: (caller line, what the model does). Returns the agent and every reply."""
    async def run():
        said = []
        async with AgentSession(llm=Script([s for _, steps in turns for s in steps])) as session:
            agent = GooseAgent("goose", caller="+15550100222", cfg=load_config())
            await session.start(agent)
            for line, _ in turns:
                r = await session.run(user_input=line)
                said.append([e.item.text_content for e in r.events if getattr(e, "type", "") == "message" and e.item.role == "assistant"])
            return agent, said
    return asyncio.run(run())


MSG = ("take_message", '{"from_name": "Sam", "message": "Dinner Saturday at seven works."}')
SAVES = lambda a: [e for e in a.log if e.startswith("message from")]


def test_a_claim_with_nothing_queued_becomes_the_confirm():
    a, said = play([("Tell him I'm bringing wine.", ["I've added that to the note."])])
    assert "added" not in " ".join(said[0]) and "pass that on" in " ".join(said[0]).lower()
    assert "take_message" in a.agenda.pending and not SAVES(a)


def test_a_yes_to_a_spoken_offer_makes_the_claim_true():
    a, said = play([("Tell him I'm bringing wine.", ["Want me to add that to the message?"]),
                    ("Yes.", ["On it, I've added that."])])
    assert "added" in " ".join(said[1]) and len(SAVES(a)) == 1 and "wine" in SAVES(a)[0]


def test_a_yes_to_a_spoken_offer_is_not_asked_again():
    a, said = play([("Tell him dinner works.", ["Want me to pass that on?"]), ("Yes.", [MSG, "Saved."])])
    assert "pass that on" not in " ".join(said[1]).lower() and len(SAVES(a)) == 1 and not a.agenda.pending


def test_a_repeat_after_the_yes_is_not_asked_again():
    a, said = play([("Tell him dinner works.", [MSG]), ("Yes.", ["Saved."]), ("Thanks.", [MSG, "All set."])])
    assert "pass that on" not in " ".join(said[2]).lower() and len(SAVES(a)) == 1 and not a.agenda.pending


def test_nothing_fires_without_a_yes():
    a, said = play([("Tell him dinner works.", [MSG])])
    assert not SAVES(a) and "take_message" in a.agenda.pending and "pass that on" in " ".join(said[0]).lower()


def test_second_message_keeps_the_first():
    wine = ("take_message", '{"from_name": "Sam", "message": "I am bringing wine."}')
    a, _ = play([("Tell him dinner works.", [MSG]), ("Yes.", ["Saved."]), ("Also, tell him I'm bringing wine.", [wine]), ("Yes.", ["Saved."])])
    assert len(SAVES(a)) == 2 and a.agenda.slots["details"] == "Dinner Saturday at seven works. I am bringing wine."
