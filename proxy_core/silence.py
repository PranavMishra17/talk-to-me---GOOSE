"""Pure silence ladder: nudge -> restate -> close, each once, never over another speaker."""
ACTIONS = ("nudge", "restate", "close")


def next_action(silent_for_s, step_done, floor_holder, agent_speaking, me="me", thresholds=(6, 12, 20)):
    """-> (action|None, new_step). step_done = rungs already fired (0..3)."""
    if agent_speaking or floor_holder not in (None, me) or step_done >= 3:
        return None, step_done
    if silent_for_s >= thresholds[step_done]:
        return ACTIONS[step_done], step_done + 1
    return None, step_done


class SilenceLadder:
    def __init__(self, me, thresholds=(6, 12, 20)):
        self.me, self.thresholds, self.step = me, tuple(thresholds), 0

    def tick(self, silent_for_s, floor_holder, speaking):
        act, self.step = next_action(silent_for_s, self.step, floor_holder, speaking, self.me, self.thresholds)
        return act

    def reset(self):
        self.step = 0
