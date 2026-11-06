# talk to me... GOOSE

Goose is a voice personal assistant that picks up when you can't. It knows who's calling, what they're allowed to hear, and tells you how it went.

Every model is a line in `config.yaml`, every personality is a file in `personalities/`, and privacy is enforced in code, not in the prompt.

## Install

You need Git and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/PranavMishra17/talk-to-me---GOOSE.git
cd talk-to-me---GOOSE
uv sync --extra nc
uv run pytest -q
```

## Keys

Create a file named `.env` in the repo root. It is gitignored, so never commit it.

```text
LIVEKIT_URL=wss://YOUR-PROJECT.livekit.cloud
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
OPENROUTER_API_KEY=
GOOSE_PHONE_NUMBER=
```

Get the first three from [cloud.livekit.io](https://cloud.livekit.io). A free account has its own credits. `OPENROUTER_API_KEY` is optional: without it Goose falls back to its keyword decider. `GOOSE_PHONE_NUMBER` is only what the web page displays.

## Try it

### 1. In the terminal (fastest)

```bash
uv run python scripts/call.py
```

Pick who you are, then type to Goose: Pranav (owner), someone in the contact book, or an unknown caller. Ctrl+C ends the call.

```bash
uv run python scripts/call.py --as muhammad
uv run python scripts/call.py --as owner --voice
uv run python scripts/call.py --as muhammad --pack jesse
```

### 2. The web app, no keys needed

Fake data, for looking around.

Mac or Linux:

```bash
GOOSE_MOCK=1 uv run uvicorn app.api:app --port 8000
```

Windows PowerShell:

```bash
$env:GOOSE_MOCK=1; uv run uvicorn app.api:app --port 8000
```

Open http://localhost:8000 for the landing page, and http://localhost:8000/app for history and **Talk to me, Goose**.

### 3. The real web app

Run these in two terminals:

```bash
uv run python -m app.worker dev
```

```bash
uv run uvicorn app.api:app --port 8000
```

Open http://localhost:8000, then press **Talk to me, Goose** or open a room. Press Ctrl+C on the worker when you're done, because a running session spends credits.

### 4. The phone

Once a LiveKit number has a dispatch rule pointing at the agent, keep the worker from step 3 running and call the number. Run only one worker per LiveKit project, or calls can land on the wrong machine.

## What's where

| Path | What it does |
|---|---|
| `app/agent.py`, `app/worker.py` | The live agent: tools, hooks and session wiring |
| `proxy_core/` | Pure logic: tiers, vault, floor, agenda, decider, echo guard |
| `app/api.py`, `web/static/` | Web API and pages |
| `personalities/` | One file per personality: plug any into any agent |
| `data/` | Mock Gmail, Slack, calendar, notes, tasks, contacts and calls, each tagged by tier |
| `config.yaml` | Models, turn-taking, limits, personas |

## Check your work

```bash
uv run pytest -q
```

```bash
uv run python scripts/harness.py --caller +15550100222 --say "Hi, it's Sam."
```

The harness runs the real agent in a real room with a scripted caller and prints latency per module. It spends a few cents, and synthetic speech can't judge turn-taking, so test that by ear. Run `uv run python tests/bench.py` for the text scenarios.
