"""Machine ear: does the console hello test (A4) with nobody at a microphone. Spends credits (a few cents a run).
  uv run python scripts/harness.py
  uv run python scripts/harness.py --say "Hi, it's Sam." --say "Tell him dinner Saturday works." --caller +15550100222
Starts the real worker, dispatches it into a real room, joins as a caller, speaks synthesised lines, and measures
end of caller speech -> first agent audio. The room and worker are always torn down. Exit 0 = every line answered in budget.
Result goes to stdout, .harness/, and the dashboard log.
"""
import argparse, asyncio, hashlib, json, os, re, subprocess, sys, time, uuid, wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import aiohttp
from livekit import api, rtc
from livekit.agents import inference

import plan
from proxy_core import latency
from proxy_core.agenda import is_bye, is_yes
from proxy_core.config import load_config, load_env

OUT = ROOT / ".harness"
SR, FRAME = 24000, 480   # 20 ms
BUDGET_S, QUIET_S, PEAK = 3.0, 1.5, 300
CLOSED = "session closed"
WARNINGS = ("slow audio generation", "preemptive generation invalidated", "error occurred", "Traceback", "using preemptive generation")


async def speech(text, voice):
    """PCM bytes for a line. Cached on disk so repeat runs cost nothing."""
    f = OUT / f"line_{hashlib.sha1(text.encode()).hexdigest()[:10]}.wav"
    if not f.exists():
        async with aiohttp.ClientSession() as http:
            # the caller's voice stays fixed, so A/B runs of the agent's models hear the same input
            tts = inference.TTS(model="cartesia/sonic-3.5", language="en", voice=voice, http_session=http, sample_rate=SR)
            pcm = b"".join([bytes(a.frame.data) async for a in tts.synthesize(text)])
            await tts.aclose()
        with wave.open(str(f), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm)
    with wave.open(str(f), "rb") as w:
        return w.readframes(w.getnframes())


def start_worker(persona, log_path):
    env = {**os.environ, "GOOSE_PERSONA": persona, "PYTHONUTF8": "1"}
    return subprocess.Popen([sys.executable, "-m", "app.worker", "dev"], cwd=ROOT, env=env,
                            stdout=open(log_path, "w", encoding="utf-8"), stderr=subprocess.STDOUT)


def stop_worker(p):
    if os.name == "nt":  # dev mode has child processes
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
    else:
        p.kill()


async def wait_registered(log_path, proc, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        if "registered worker" in text:
            return
        if proc.poll() is not None:
            raise RuntimeError("worker exited early:\n" + text[-1500:])
        await asyncio.sleep(0.25)
    raise TimeoutError("worker never registered")


class Caller:
    def __init__(self, room):
        self.room, self.src = room, rtc.AudioSource(SR, 1, queue_size_ms=100)
        self.pending, self.first_after, self.last_audio, self.said = bytearray(), None, 0.0, []
        self.speaking_done = asyncio.Event()
        self.listen_from, self.t0, self.events = time.time(), time.time(), []
        room.on("track_subscribed", self._track)
        room.on("participant_attributes_changed", self._attrs)
        self.gone, self.state = None, None
        room.on("disconnected", lambda reason: setattr(self, "gone", f"{time.time() - self.t0:.2f}s {reason}"))
        room.register_text_stream_handler("lk.transcription", self._text)

    def _note(self, what):
        self.events.append(f"{time.time() - self.t0:.2f}s {what}")

    def _track(self, track, pub, who):
        self._note(f"track {who.identity} {track.kind}")
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            asyncio.ensure_future(self._hear(track)).add_done_callback(
                lambda f: f.cancelled() or not f.exception() or self._note(f"hear failed: {f.exception()!r}"))

    def _attrs(self, changed, who):
        if "lk.agent.state" in changed:
            self._note(f"state {changed['lk.agent.state']}")
        if "goose.state" in changed:
            self.state = json.loads(changed["goose.state"])
            self._note(f"goose.state focus={self.state['focus']} slots={self.state['slots']} pending={self.state['pending_confirm']} log={self.state['log'][-1:]}")

    def _text(self, reader, who):
        async def read():
            txt = await reader.read_all()
            if txt.strip() and who != self.room.local_participant.identity:
                self.said.append(txt.strip())
        asyncio.ensure_future(read())

    async def _hear(self, track):
        async for ev in rtc.AudioStream(track, sample_rate=SR, num_channels=1):
            if max(abs(s) for s in ev.frame.data[::8]) > PEAK:
                self.last_audio = time.time()
                if self.first_after is None and self.last_audio >= self.listen_from:
                    self.first_after = self.last_audio

    async def pump(self):  # continuous mic: silence between lines, as a real caller has
        size = FRAME * 2
        while True:
            chunk = bytes(self.pending[:size])
            del self.pending[:size]
            speaking = bool(chunk)
            chunk = chunk.ljust(size, b"\0")
            await self.src.capture_frame(rtc.AudioFrame(chunk, SR, 1, FRAME))
            if speaking and not self.pending:
                self.speaking_done.set()

    async def wait_reply(self, timeout):
        end = time.time() + timeout
        while self.first_after is None and time.time() < end:
            await asyncio.sleep(0.02)
        if self.first_after is None:
            return None
        got = self.first_after
        while time.time() - self.last_audio < QUIET_S:
            await asyncio.sleep(0.05)
        return got

    async def say(self, pcm):
        self.speaking_done.clear()
        self.pending.extend(pcm)
        await self.speaking_done.wait()
        self.listen_from, self.first_after = time.time(), None
        return self.listen_from


async def session(a, log_path, proc):
    url, key, secret = (os.environ[k] for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"))
    pack_voice = None
    lines = [(t, await speech(t, pack_voice)) for t in a.say]
    await wait_registered(log_path, proc)
    name = f"harness-{uuid.uuid4().hex[:8]}"
    lk, room, res = api.LiveKitAPI(url, key, secret), rtc.Room(), {"room": name, "turns": []}
    pump = None
    try:
        await lk.room.create_room(api.CreateRoomRequest(name=name, empty_timeout=30))
        await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
            agent_name=a.persona, room=name))
        token = api.AccessToken(key, secret).with_identity("harness-caller").with_kind("sip" if a.sip else "standard").with_attributes({"sip.phoneNumber": a.caller} if a.caller else {}).with_grants(
            api.VideoGrants(room_join=True, room=name)).to_jwt()
        c = Caller(room)
        await room.connect(url, token)
        await room.local_participant.publish_track(rtc.LocalAudioTrack.create_audio_track("mic", c.src),
                                                   rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
        pump = asyncio.ensure_future(c.pump())
        t0 = time.time()
        got = await c.wait_reply(30)
        res["greeting_s"] = round(got - t0, 2) if got else None
        for text, pcm in lines:
            eos = await c.say(pcm)
            got = await c.wait_reply(15)
            res["turns"].append({"at": time.strftime("%H:%M:%S", time.localtime(eos)), "said": text,
                                 "first_audio_s": round(got - eos, 2) if got else None})
        await asyncio.sleep(0.5 + a.hold)  # the last transcript; then a silent caller, for nudges and hang-ups
        if is_bye(a.say[-1]) or is_yes(a.say[-1]):   # the agent must close it: checked while the room is still alive
            end = time.time() + 10
            while not (closed := CLOSED in log_path.read_text(encoding="utf-8", errors="replace")) and time.time() < end:
                await asyncio.sleep(0.25)
            res["closed"] = closed
        res["agent_said"], res["events"], res["disconnected"], res["state"] = c.said, c.events, c.gone, c.state
        res["server_state"] = [json.loads(p.attributes["goose.state"]) for p in (await lk.room.list_participants(
            api.ListParticipantsRequest(room=name))).participants if "goose.state" in p.attributes]
    finally:
        if pump:
            pump.cancel()
        await room.disconnect()
        try:
            await lk.room.delete_room(api.DeleteRoomRequest(room=name))   # this is what stops the credit burn
        finally:
            await lk.aclose()
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--say", action="append")
    ap.add_argument("--persona", default="ash")
    ap.add_argument("--caller", default="")
    ap.add_argument("--hold", type=float, default=0, help="stay silent this many seconds after the last line")
    ap.add_argument("--sip", action="store_true", help="join as a SIP participant, so hang-up and BVC run the phone path")
    ap.add_argument("--no-log", action="store_true", help="skip the dashboard log line")
    a = ap.parse_args()
    a.say = a.say or ["Hi, it's Sam."]
    load_env()
    OUT.mkdir(exist_ok=True)
    log_path = OUT / "worker.log"
    proc = start_worker(a.persona, log_path)
    try:
        res = asyncio.run(asyncio.wait_for(session(a, log_path, proc), 150 + a.hold))
    finally:
        stop_worker(proc)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    res["log_hits"] = {w: text.count(w) for w in WARNINGS if w in text}
    res["actions"] = re.findall(r"(\d\d:\d\d:\d\d),\d+ .*ACTION (.*?) *(?:|$)", text, re.M)   # the task log, worker wall clock
    res["modules"] = latency.turns(latency.parse(text))
    ok = bool(res["turns"]) and all((t["first_audio_s"] or 99) <= BUDGET_S for t in res["turns"]) and res.get("closed", True)
    res["pass"] = ok
    (OUT / "last.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "modules"}, indent=1))
    print(latency.table(res["modules"]))
    if not a.no_log:
        plan.log(f"harness {'PASS' if ok else 'FAIL'}: greeting {res.get('greeting_s')} s, reply first audio "
                 f"{[t['first_audio_s'] for t in res['turns']]} s (budget {BUDGET_S} s); modules {res['modules'][1:]}", who="harness")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
