# CP-010 — FastAPI backend service

> Status: ready
> Depends on: CP-008
> Phase: 3 App surface

## Objective
Expose the pipeline as a FastAPI service (`:8000`) that the Brand Kit Gallery and other
clients consume: start a run, stream live events, serve assets/brand guide/zip. This is
the backend half of "project completeness" (rubric 3).

## Scope
- `src/orchestrator/api.py` — FastAPI app with the routes in `05-frontend.md`:
  - `POST /api/runs` (multipart: brief, image, options) → `{run_id}` (starts `run_pipeline` as a background task).
  - `GET /api/runs/{id}` → current `kit_manifest.json` + stage.
  - `GET /api/runs/{id}/events` → SSE stream tailing `run.log` + `orchestrator_log.json`.
  - `GET /api/runs/{id}/assets/{name}` → serve PNG (with content-type).
  - `GET /api/runs/{id}/brand_guide` → serve `brand_guide.md`.
  - `GET /api/runs/{id}/kit.zip` → zip `brand_kit/`.
  - `GET /api/health` → liveness + dependency probes (Ollama/ComfyUI/Stepfun reachable).
- Run registry: in-memory dict of `run_id → asyncio.Task` (single-user local app).
- CORS for `:5173`; bind `0.0.0.0:8000` for LAN access.
- Structured request logging; never logs secrets or image bytes.

## Non-goals
- No auth/multi-tenant (single-user local).
- No persistence beyond the `runs/` filesystem (no DB).
- No frontend (CP-011).

## Constraints
- One run at a time on the Spark (GPU constraint) — `POST /api/runs` returns 409 if a run is active, with the active `run_id`.
- SSE must auto-close on run completion; clients fall back to polling.
- All routes typed with Pydantic models; no untyped JSON.
- **Security (see `07-security-and-tokens.md` §B):**
  - `run_id` validated with `RUN_ID_REGEX`; all file-serving routes validate `name` as a
    bare basename, resolve the final path, and assert it is inside `runs/<run_id>/` (S1/S7).
  - CORS restricted to `CORS_ALLOWED_ORIGINS` only — never `*` (S2).
  - Multipart upload capped at `MAX_UPLOAD_MB`; image validated by parsing with Pillow (S3).
  - SSE tailer allowlists event fields; never streams raw env or full user-pasted text (S5).
- This service is the **single secrets boundary** — the only component that loads `.env`.

## Acceptance tests
- [ ] `pytest tests/test_api.py` — mocked pipeline: `POST /api/runs` returns `{run_id}`; `GET /api/runs/{id}` returns a manifest; SSE yields ≥ 3 events then closes.
- [ ] Concurrent `POST /api/runs` while a run is active → 409.
- [ ] Path-traversal: `GET /api/runs/{id}/assets/..%2F..%2F.env` (and `..` variants) → 404/400, never file contents.
- [ ] Oversize upload (> `MAX_UPLOAD_MB`) → 413; non-image MIME → 400.
- [ ] CORS `Access-Control-Allow-Origin` reflects the allowlist only (no `*`).
- [ ] `GET /api/runs/{id}/kit.zip` returns a valid zip containing the brand kit files.
- [ ] `GET /api/health` reports Ollama/ComfyUI/Stepfun reachability.
- [ ] Live smoke (manual): `uvicorn src.orchestrator.api:app` serves a real run end-to-end.
- [ ] `make lint && make typecheck` pass.

## Relevant context
- Design refs: `05-frontend.md` (API contract), `06-deployment.md` (port 8000, `make up`).
- The SSE stream reuses the event emitter hook from CP-008.
- Single-flight constraint comes from the GB10 VRAM reality (CP-007).
