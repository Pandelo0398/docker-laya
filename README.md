# docker-laya

[![Publish Docker image](https://github.com/chneau/docker-laya/actions/workflows/publish.yml/badge.svg)](https://github.com/chneau/docker-laya/actions/workflows/publish.yml)
[![Docker Image](https://img.shields.io/badge/docker_image-ghcr.io%2Fchneau%2Flaya-blue?logo=docker)](https://ghcr.io/chneau/laya)

Dockerized [Laya](https://huggingface.co/convaiinnovations/laya) prediction
service: loads one or more checkpoints behind a router, then serves typed
decisions (choice / score / noul) over HTTP, auto-routed by language or pinned
with `model`. Also supports TypeSafe API compatibility via `/v1/systemone`.

Built and published for `linux/amd64` and `linux/arm64`.

---

## ✨ Features

- 🔀 **Multi-Checkpoint Routing**: bundles `english`, `multilingual` and
  `typed-decisions`, auto-selected by language or pinned per request.
- 🎯 **Typed Decisions**: `choice` / `score` / `noul` questions with calibrated
  probabilities, confidence and action probability.
- 🤝 **TypeSafe API Compatibility**: drop-in `/v1/systemone` endpoint compatible
  with TypeSafe request/response schemas.
- 🔐 **Timing-Safe Auth**: API keys (`X-API-Key` / `Authorization: Bearer`) and
  HTTP Basic, compared in constant time.
- 📑 **Interactive OpenAPI Docs**: Swagger UI (`/docs`), ReDoc (`/redoc`) and the
  raw schema at `/openapi.json`.
- 🧰 **Built-in Presets**: ready-made question sets (`triage`, `email`, `guard`,
  `moderation`, `router`).
- 📦 **Bulk Inference**: `/predict/bulk` over many states, with per-state
  questions/model and isolated errors.
- 🔎 **Detection & Email Helpers**: `/detect` (script/language) and
  `/email/state` (clean + structure an email).
- 🧩 **Flexible State**: string, JSON object, or conversation turns; criteria
  values may be any JSON (dicts/lists/numbers are rendered as compact JSON).
- 🛡️ **Non-Root**: runs as unprivileged `appuser` (uid `10001`).
- 📦 **Multi-Architecture**: supports both `linux/amd64` and `linux/arm64`.
- 🩺 **Healthcheck**: dedicated `/healthz` endpoint and container `HEALTHCHECK`.
- 🪶 **CPU-Only Torch**: uses the PyTorch CPU wheel index (no CUDA), roughly
  `0.35s` per predict on CPU.

---

## 🚀 Quickstart

Pull and run the published image:

```bash
docker pull ghcr.io/chneau/laya
docker run -d -p 8000:8000 -e API_KEYS=key1 -v hf-cache:/data/hf ghcr.io/chneau/laya
```

### 🏷️ Docker Image Tags & Model Variants

Multi-architecture images (`linux/amd64` and `linux/arm64`) are published to GitHub Container Registry under several tags:

| Image Tag | Preloaded Models | Image Size | Description |
| :--- | :--- | :--- | :--- |
| `ghcr.io/chneau/laya:latest` (or `v0.5.0`) | None (Dynamic) | ~300 MB | **Slim / Default**: Small image size. Downloads model on first run into `/data/hf`. |
| `ghcr.io/chneau/laya:english` | `english` | ~1.3 GB | **Instant Startup (English)**: Pre-baked English checkpoint, offline-ready. |
| `ghcr.io/chneau/laya:multilingual` | `multilingual` | ~1.8 GB | **Instant Startup (Multilingual)**: Pre-baked multilingual checkpoint. |
| `ghcr.io/chneau/laya:typed-decisions` | `typed-decisions` | ~1.3 GB | **Instant Startup (Typed Decisions)**: Pre-baked typed decisions checkpoint. |
| `ghcr.io/chneau/laya:all` | All 3 models | ~3.5 GB | **Full Bundle**: All checkpoints pre-baked for zero-latency multi-model routing. |

#### Running a Pre-baked Image (Instant Startup & Air-gapped / Offline)

```bash
docker run -d -p 8000:8000 -e API_KEYS=key1 ghcr.io/chneau/laya:english
```

### Check Health

```bash
curl http://localhost:8000/healthz
```

### View Interactive API Documentation

- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Raw OpenAPI Specification**:
  [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

---

## 📇 Endpoints

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/healthz` | no | Liveness + resident models |
| `GET` | `/models` | yes* | Available and loaded checkpoints |
| `GET` | `/presets` | yes* | Built-in question sets |
| `POST` | `/detect` | yes* | Script/language detection (what routing uses) |
| `POST` | `/email/state` | yes* | Clean + structure an email as a state |
| `POST` | `/predict` | yes* | Typed questions over one state |
| `POST` | `/predict/bulk` | yes* | Same questions over many states |
| `POST` | `/v1/systemone` | yes* | SystemOne / TypeSafe compatible prediction |

\* Enforced only when `API_KEYS` and/or `BASIC_AUTH` is set. Any of these works:

```bash
-H 'X-API-Key: key1'
-H 'Authorization: Bearer key1'
-u admin:secret              # HTTP Basic
```

---

## 🧠 Predicting

### Standard Prediction (`POST /predict`)

```bash
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

---

### SystemOne / TypeSafe Compatible Prediction (`POST /v1/systemone`)

```bash
curl -X POST localhost:8000/v1/systemone -H 'Authorization: Bearer key1' -H 'Content-Type: application/json' -d '{
  "state": "I was billed twice. Please refund the duplicate today.",
  "model": "laya-english",
  "questions": {
    "department": {"type": "choice", "instructions": "Which team?", "criteria": {"billing": "refunds", "technical": "bugs", "sales": "purchases"}},
    "urgency":    {"type": "score",  "instructions": "How urgent?", "criteria": ["not urgent", "soon", "critical"]},
    "refund":     {"type": "noul",   "instructions": "Does the customer ask for money back?"}
  }
}'
```

```json
{
  "model": "laya-english",
  "answers": {
    "department": {"type": "choice", "choice": "billing", "probabilities": {"billing": 0.96, "technical": 0.02, "sales": 0.02}, "confidence": 0.82},
    "urgency":    {"type": "score", "score": 1.36, "legend": {"0": "not urgent", "1": "soon", "2": "critical"}, "confidence": 0.09},
    "refund":     {"type": "noul", "noul": 0.82}
  },
  "usage": {"input_tokens": 132, "output_tokens": 0}
}
```

Supported model names for TypeSafe requests:
`laya-english`, `laya-multilingual`, `laya-typed-decisions`.

---

## ⚙️ Configuration & Environment Variables

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

---

## 🐳 Docker Compose Example

```yaml
services:
  laya:
    image: ghcr.io/chneau/laya
    ports:
      - "8000:8000"
    environment:
      - API_KEYS=replace_with_your_strong_api_key
      - MODELS=english,multilingual
    volumes:
      - hf-cache:/data/hf
    restart: unless-stopped

volumes:
  hf-cache:
```

### Build Locally

```bash
cp .env.example .env          # set API_KEYS
make up                       # docker compose up -d --build
```

---

## 🛠️ Generating Client SDKs

The full OpenAPI 3.1 schema is saved directly in the repository as
[`openapi.json`](./openapi.json) (and served at `/openapi.json`). You can
generate type-safe API clients for TypeScript, Go, Python, etc.:

### TypeScript / Fetch Client (using `openapi-typescript`)

```bash
npx openapi-typescript ./openapi.json -o laya-client.d.ts
```

### Multi-language Client (using OpenAPI Generator)

```bash
# Generate Python SDK
npx @openapitools/openapi-generator-cli generate -i openapi.json -g python -o ./clients/python

# Generate Go SDK
npx @openapitools/openapi-generator-cli generate -i openapi.json -g go -o ./clients/go
```

To regenerate the schema file at any time:

```bash
make openapi
```

---

## 🧪 Testing Locally

```bash
# Lint and format check
make check

# Build and run the container
docker build -t laya-api:test .
docker run --rm -p 8000:8000 -e API_KEYS=test laya-api:test
```

The CI workflow also runs a container smoke test (`/healthz` + `/predict`)
before publishing.

### Make targets

```sh
make openapi                    # regenerate openapi.json
make up / down / build / logs   # docker
make run                        # uvicorn --reload on :8000
make format / check / fix       # ruff
```

---

## 📝 Notes

- Runs as non-root (`appuser`, uid 10001); the `hf-cache` volume inherits that
  ownership. If you bind-mount your own cache, make sure uid 10001 can write it.
- Torch uses the CPU wheel index (`pyproject.toml`); ~0.35s per predict on CPU.
- The router loads once behind a lock, so requests are serialised per process.
- `/predict/bulk` loops (laya's public API is single-state); it does not batch.

---

## 📄 License

MIT © [chneau](https://github.com/chneau)
