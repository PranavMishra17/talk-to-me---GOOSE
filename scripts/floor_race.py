"""Proves the floor's one load-bearing claim: two workers claiming at once get exactly one winner, with no CAS.
Two real room connections call RoomFloor.take() together, no LLM or audio, so it costs almost nothing.
  uv run python scripts/floor_race.py --rounds 20
Prints winners per round, and how long a metadata write takes to reach the other participant.
"""
import argparse, asyncio, json, os, statistics, sys, time, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from livekit import api, rtc

from app.room_floor import RoomFloor
from proxy_core.config import load_config, load_env


async def main(rounds):
    load_env()
    url, key, secret = (os.environ[k] for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"))
    name, cfg = f"race-{uuid.uuid4().hex[:8]}", load_config()
    lk = api.LiveKitAPI(url, key, secret)
    await lk.room.create_room(api.CreateRoomRequest(name=name, empty_timeout=30))
    rooms = [rtc.Room(), rtc.Room()]
    try:
        for i, r in enumerate(rooms):
            await r.connect(url, api.AccessToken(key, secret).with_identity(f"w{i}").with_grants(api.VideoGrants(room_join=True, room=name)).to_jwt())
        a, b = RoomFloor(rooms[0], lk, "ash", cfg), RoomFloor(rooms[1], lk, "maya", cfg)
        winners, rtt, seen = [], [], []
        for n in range(rounds):
            t = time.time()
            won = await asyncio.gather(a.take(t), b.take(t))
            winners.append(sum(won))
            for f in (a, b):
                await f.release()
            while rooms[0].metadata != rooms[1].metadata:
                await asyncio.sleep(0.01)
            # plain write: time to return, and time for the other side to see it
            body, t0 = json.dumps({"holder": None, "since": n}), time.time()
            done = asyncio.ensure_future(lk.room.update_room_metadata(api.UpdateRoomMetadataRequest(room=name, metadata=body)))
            while rooms[1].metadata != body:
                await asyncio.sleep(0.002)
            seen.append(time.time() - t0)
            await done
            rtt.append(time.time() - t0)
        print(json.dumps({"rounds": rounds, "winners_per_round": winners, "exactly_one": winners.count(1),
                          "write_return_ms": [round(statistics.median(rtt) * 1000), round(max(rtt) * 1000)],
                          "write_to_other_side_ms": [round(statistics.median(seen) * 1000), round(max(seen) * 1000)]}))
    finally:
        for r in rooms:
            await r.disconnect()
        await lk.room.delete_room(api.DeleteRoomRequest(room=name))
        await lk.aclose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=20)
    asyncio.run(main(ap.parse_args().rounds))
