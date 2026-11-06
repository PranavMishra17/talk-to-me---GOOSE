"""LiveKit-touching: the shared floor across two agent worker processes, stored in room metadata.

Room metadata has no compare-and-swap, so a claim is write, wait, read back: the server keeps the last write, both
agents see that same value once it has propagated, and only the agent named in it speaks.
ponytail: SETTLE_S is the ceiling. If two claims land together and the later write takes longer than SETTLE_S to
reach the first claimer, both speak for that turn. Upgrade: one arbiter process, or LiveKit RPC.
"""
import asyncio
import logging
import time

from livekit import api, rtc

from proxy_core import floor

logger = logging.getLogger("goose")
SETTLE_S = 0.25   # must exceed metadata propagation; see FLOOR lines in the worker log
WAIT_S = 25.0     # longer than the lease, so a stuck holder cannot cost the other agent its line


class RoomFloor:
    def __init__(self, room, lk, me, cfg):
        self.room, self.lk, self.me = room, lk, me
        self.cap, self.lease_s = cfg["limits"]["max_agent_streak"], cfg["limits"]["floor_lease_s"]
        self.held, self.expected = False, False
        self.lock = asyncio.Lock()

    def expect_peer(self, on=True):
        self.expected = on

    def crowded(self):
        return self.expected or any(p.kind == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT for p in self.room.remote_participants.values())

    def read(self):
        try:
            return floor.FloorState.from_json(self.room.metadata or None)
        except (ValueError, TypeError):
            return floor.FloorState()

    def yielded(self):
        return floor.must_yield(self.read(), self.cap)

    async def _write(self, st):
        await self.lk.room.update_room_metadata(api.UpdateRoomMetadataRequest(room=self.room.name, metadata=st.to_json()))

    async def take(self, human_stopped=None):
        """True = speak. human_stopped: answering the human turn that ended then; a lost race then means silence.
        Fails open: a metadata error must not mute the call."""
        t0, end = time.time(), time.time() + WAIT_S
        try:
            while time.time() < end:
                async with self.lock:
                    verdict, st = floor.try_claim(self.read(), self.me, time.time(), human_stopped, self.cap, self.lease_s)
                    if verdict == "drop":
                        logger.info("FLOOR %s drop holder=%s streak=%s", self.me, st.holder, st.agent_streak)
                        return False
                    if verdict == "take":
                        if self.held:
                            return True
                        await self._write(st)
                        await asyncio.sleep(SETTLE_S)
                        now = self.read()
                        if now.holder == self.me:
                            self.held = True
                            logger.info("FLOOR %s take %.0f ms streak=%s", self.me, (time.time() - t0) * 1000, now.agent_streak)
                            return True
                        logger.info("FLOOR %s lost race to %s", self.me, now.holder)
                        if human_stopped is not None:
                            return False
                await asyncio.sleep(0.05)
            logger.info("FLOOR %s gave up waiting", self.me)
            return False
        except Exception as e:
            logger.warning("floor take failed, speaking anyway: %s", e)
            return True

    async def release(self):
        async with self.lock:
            if not self.held:
                return
            self.held = False
            try:
                await self._write(floor.release_floor(self.read(), self.me, time.time()))
                logger.info("FLOOR %s release", self.me)
            except Exception as e:
                logger.warning("floor release failed; the lease frees it: %s", e)
