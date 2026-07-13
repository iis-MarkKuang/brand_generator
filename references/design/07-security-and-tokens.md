# 07 — Security & Token-Budget Design

> Cross-cutting requirements every change packet must honor. Findings from the
> architecture/roadmap review. Referenced by `docs/architecture.md` §9 and the
> `.cursor/rules/security.mdc` rule.

## A. Single secrets boundary

**Principle:** only the **FastAPI orchestrator service (`:8000`)** loads `.env` and holds
API keys. No other component (OpenClaw skill, NemoClaw sandboxed agent, frontend, CLI in
sandboxed mode) holds secrets.

- The OpenClaw skill (CP-009) and the NemoClaw-sandboxed agent (CP-012) **call the
  orchestrator over `localhost:8000`** instead of loading `.env`.
- The standalone CLI (`src/orchestrator/cli.py`) may load `.env` **only** for local
  testing / golden runs outside the sandbox.
- Consequence: CP-009 depends on CP-010 (the skill talks to the API), and the critical
  path becomes `…CP-008 → CP-010 → CP-009…`. ROADMAP updated accordingly.
- The NemoClaw sandbox filesystem policy mounts **no secret files**; the Stepfun/NIM
  keys live only in the orchestrator process env (outside the sandbox).

## B. Application security

| ID | Risk | Mitigation | Owner CP |
|---|---|---|---|
| S1 | **Path traversal** via `/api/runs/{id}/assets/{name}` (`../../.env`) | Validate `run_id` with regex `^[A-Za-z0-9_-]{1,64}$`; validate `name` is a bare basename (reject `/`, `\`, `..`, leading `.`); resolve final path and assert it stays inside `runs/<id>/`. | CP-010 |
| S2 | **CORS wildcard** on LAN | `CORS_ALLOWED_ORIGINS` explicit list (default `http://localhost:5173,http://127.0.0.1:5173` + the Spark LAN origin). Never `*`. | CP-010 |
| S3 | **Upload DoS / disk fill** | Max upload size `MAX_UPLOAD_MB` (default 10); reject oversize early; validate image MIME via Pillow parse (not extension). | CP-010 |
| S4 | **Telegram public bot → unauthorized GPU drain** | `TELEGRAM_ALLOWED_CHAT_IDS` allowlist; bot drops messages from unlisted chats before any GPU work. | CP-012 |
| S5 | **Secret leak via SSE/run.log** | Structured logger never logs secrets (rule); additionally the SSE tailer allowlists event fields (no raw env, no full prompts containing user-pasted secrets); run.log is run-scoped under `runs/<id>/`. | CP-008, CP-010 |
| S6 | **Data egress disclosure** | Brief + reference image go to Stepfun VLM; on NIM failover, reasoning **text** goes to NVIDIA cloud (never images). Document in `docs/deployment.md` data-flow section; provide `NO_CLOUD_VISION=1` degraded mode that disables the VLM (analysis falls back to a text-only heuristic). | CP-003, CP-013, CP-016 |
| S7 | **File serving confined** | All `/api/runs/{id}/**` responses resolve paths under `runs/<id>/` and reject escapes; kit.zip built only from `brand_kit/`. | CP-010 |
| S8 | **Sandbox network policy** | NemoClaw deny-by-default allowlist: `127.0.0.1` (orchestrator/ComfyUI/Ollama), `api.stepfun.com`, `integrate.api.nvidia.com` (only if routing enabled). Verify by a negative test (blocked host). | CP-012 |
| S9 | **Secrets in git** | `tools/check-secrets.sh` before every commit; `.env` gitignored; CI runs the check. | all / CP-015 |

## C. Token-explosion budget

The pipeline is bounded by design; these caps make it explicit and enforceable.

| ID | Risk | Cap / rule | Owner CP |
|---|---|---|---|
| T1 | **VLM image tokens × critic loop** | Up to `assets × (1 + max_retries)` critic image calls. Default 5×3 = 15. Global hard cap `MAX_TOTAL_VLM_CALLS` (default 25). | CP-008 |
| T2 | **Image detail cost** | `image_url.detail`: first critique = `high` (legibility needs resolution); re-checks (attempt ≥ 2) = `low`. Configurable. | CP-002, CP-006 |
| T3 | **Large source images** | Pre-resize any image sent to the VLM to ≤ 1024px on the long side before base64 encoding (bounds tokens + payload). | CP-002 |
| T4 | **Director context growth** | The Art Director's tool-calling context holds **text only**: `brand_dna` (text) + `asset_manifest` (text) + per-asset `CriticResult` (text). **Never images.** Append only the failing asset's feedback, not all prior results. | CP-004, CP-008 |
| T5 | **Re-plan explosion** | On a single asset failure, call `rewrite_prompt` for **that asset only**. Never re-plan the whole manifest inside the loop. | CP-008 |
| T6 | **Render explosion** | Global hard cap `MAX_TOTAL_RENDERS` (default 20) across the run. | CP-008 |
| T7 | **Prompt length** | `AssetSpec.flux_prompt` ≤ 600 chars (CLIP truncation + token hygiene); `negative_prompt` ≤ 300 chars. Enforced in the Pydantic schema. | CP-001 |
| T8 | **Run wall-clock** | Hard `RUN_TIMEOUT_S` (default 600); the orchestrator cancels and assembles a partial kit on timeout. | CP-008 |
| T9 | **Plan caching** | Cache `plan_assets` per `(brand_dna_hash, asset_types)` so iterate-"tweak the banner" runs don't re-plan. | CP-004 |

## D. Config additions (CP-001)

New `Settings` fields (with safe defaults), all in `.env.example`:

```
MAX_UPLOAD_MB=10
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
TELEGRAM_ALLOWED_CHAT_IDS=
MAX_TOTAL_VLM_CALLS=25
MAX_TOTAL_RENDERS=20
RUN_TIMEOUT_S=600
NO_CLOUD_VISION=0
VLM_IMAGE_DETAIL_FIRST=high
VLM_IMAGE_DETAIL_RECHECK=low
```

## E. Acceptance cross-check (must be reflected in CP acceptance tests)

- CP-010: path-traversal request returns 404/400 (not file contents); oversize upload rejected; CORS reflects allowlist only.
- CP-012: sandbox has no secret files; bot drops an unlisted-chat message; blocked-host egress test fails.
- CP-008: a run with an injected always-fail critic stops at `MAX_TOTAL_VLM_CALLS`/`MAX_TOTAL_RENDERS` (no runaway); partial kit assembled.
- CP-006: re-check calls use `detail=low` (assert in mock).
- CP-004: director context never contains image data (assert in mock).
- CP-001: schema rejects a `flux_prompt` > 600 chars; `run_id` regex enforced.
