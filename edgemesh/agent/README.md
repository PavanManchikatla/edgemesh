# agent

Python agent that persists a node identity, registers with coordinator, and sends heartbeats.

## Run

```bash
uv sync --dev
cp .env.example .env
PYTHONPATH=src uv run python main.py
```

## Shared Secret

If coordinator sets `EDGE_MESH_SHARED_SECRET`, set the same value in agent `.env`.
The agent automatically sends `X-EdgeMesh-Secret` on register/heartbeat calls.
