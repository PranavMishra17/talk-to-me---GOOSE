# talk to me... GOOSE

Network of personal assistants on LiveKit: Ash (Pranav) can summon Maya (Rohan) into the same room.
This repo is a **lab**. Pure logic lives in `proxy_core/` (no livekit imports) and is ported into the
organizers' starter kit tomorrow. 

Keys come from a local `.env` you create yourself (loaded with python-dotenv, never printed, never committed): `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `OPENROUTER_API_KEY`.

```bash
uv sync                                  # install
uv run pytest                            # unit tests, zero network, free
uv run python tests/bench.py             # six session.run scenarios (spends LLM credits; NOT run tonight)
uv run python -m app.worker dev          # register Ash with Cloud
uv run python -m app.worker console      # talk to Ash locally (credits; Ctrl+C when done)
```

## Frontend

No keys needed. This serves the page with fake data from `web/mock-state.json`:

```bash
GOOSE_MOCK=1 uv run uvicorn app.api:app --port 8000     # PowerShell: $env:GOOSE_MOCK=1; uv run uvicorn app.api:app --port 8000
```

Open http://localhost:8000 and press New call. Change only `web/`. The API is five calls:

| Call | Returns |
|---|---|
| `GET /api/rooms` | `{dial_in, rooms: [{room, people}]}`, newest first; the page follows the newest call |
| `GET /api/tasks` | finished calls, newest first; shape of `web/mock-tasks.jsonl` |
| `POST /api/rooms` | `{room}` |
| `GET /api/rooms/{room}` | the shape of `web/mock-state.json`; poll every second |
| `POST /api/rooms/{room}/token` with `{identity}` | `{url, token}` for LiveKit JS |

Need a new field? Add it to `web/mock-state.json` and tell Pranav, so the worker publishes it.
