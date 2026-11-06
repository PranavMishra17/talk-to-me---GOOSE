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
