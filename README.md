# Laya API

Dockerized [Laya](https://huggingface.co/convaiinnovations/laya) prediction
service: loads one or more checkpoints behind a router, then serves typed
decisions (choice / score / noul) over HTTP, auto-routed by language or pinned
with `model`. Docs: `/docs` (Swagger UI) and `/openapi.json`.

## Quick start

```sh
cp .env.example .env          # set API_KEYS
make up                       # docker compose up -d --build
```

First start downloads the checkpoint (~1 GB) into the `hf-cache` volume.
Bake it into the image for instant/offline startup with `PRELOAD_MODEL=1`.

## Endpoints

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/healthz` | no | Liveness + resident models |
| `GET` | `/models` | yes* | Available and loaded checkpoints |
| `GET` | `/presets` | yes* | Built-in question sets |
| `POST` | `/detect` | yes* | Script/language detection (what routing uses) |
| `POST` | `/email/state` | yes* | Clean + structure an email as a state |
| `POST` | `/predict` | yes* | Typed questions over one state |
| `POST` | `/predict/bulk` | yes* | Same questions over many states |

\* Enforced only when `API_KEYS` and/or `BASIC_AUTH` is set. Any of these works:

```sh
-H 'X-API-Key: key1'
-H 'Authorization: Bearer key1'
-u admin:secret              # HTTP Basic
```

## Usage

```sh
curl -X POST localhost:8000/predict -H 'X-API-Key: key1' -H 'Content-Type: application/json' -d '{
  "state": "I was billed twice. Please refund the duplicate today.",
  "questions": {
    "department": {"type": "choice", "instructions": "Which team?", "criteria": {"billing": "refunds", "technical": "bugs", "sales": "purchases"}},
    "urgency":    {"type": "score",  "instructions": "How urgent?", "criteria": ["not urgent", "soon", "critical"]},
    "refund":     {"type": "noul",   "instructions": "Does the customer ask for money back?"}
  }
}'
```

```json
{
  "model": "laya-rl-agent",
  "answers": {
    "department": {"type": "choice", "choice": "billing", "probabilities": {"billing": 0.96, "technical": 0.02, "sales": 0.02}, "confidence": 0.82},
    "urgency":    {"type": "score", "score": 1.36, "legend": {"0": "not urgent", "1": "soon", "2": "critical"}, "confidence": 0.09},
    "refund":     {"type": "noul", "noul": 0.82, "confidence": 0.82}
  },
  "usage": {"input_tokens": 132, "output_tokens": 0},
  "routing": {"model": "english", "reason": "English Latin text"}
}
```

`state` accepts a string, JSON object, or list of conversation turns. Criteria
values may be strings or any JSON value (dicts/lists/numbers are rendered as
compact JSON), and `noul` accepts optional `{"true": ..., "false": ...}` text.

**Routing** — omit `model` to auto-select by language (see `/detect`), or pin
`"model": "english" | "multilingual" | "typed-decisions"`. The response includes
`routing` with the chosen checkpoint and reason.

**Presets** — skip `questions` and pass `"preset": "triage"` (one of `triage`,
`email`, `guard`, `moderation`, `router`); list them at `GET /presets`.

**Bulk** — use `states` with shared `questions`/`preset`/`model`, or `items` to
override questions and model per state. Returns `{"count": N, "results": [...]}`
with per-state errors isolated as `{"ok": false, "error": "..."}`.

## Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `API_KEYS` | *(empty)* | Comma-separated keys; empty disables API-key auth. |
| `BASIC_AUTH` | *(empty)* | Comma-separated `user:password` pairs. |
| `MAX_BULK_ITEMS` | `256` | Max states per `/predict/bulk`. |
| `PORT` | `8000` | HTTP port (host and container). |
| `MODELS` | `english` | Checkpoints to preload: `english`, `multilingual`, `typed-decisions`. |
| `MODEL_ID` | `convaiinnovations/laya` | Optional repo override (mirror/local path). |
| `MODEL_SUBFOLDER` | *(empty)* | Subfolder for the English checkpoint. |
| `DEVICE` | `cpu` | `cpu` or `cuda`. |
| `HF_HOME` | `/data/hf` | HF cache (persisted via volume). |

Preload `MODELS=english,multilingual` to route languages without reloading.

## Make targets

```sh
make up / down / build / logs   # docker
make run                        # uvicorn --reload on :8000
make format / check / fix       # ruff
```

## Notes

- Runs as non-root (`appuser`, uid 10001); the `hf-cache` volume inherits that
  ownership. If you bind-mount your own cache, make sure uid 10001 can write it.
- Torch uses the CPU wheel index (`pyproject.toml`); ~0.35s per predict on CPU.
- The router loads once behind a lock, so requests are serialised per process.
- `/predict/bulk` loops (laya's public API is single-state); it does not batch.
