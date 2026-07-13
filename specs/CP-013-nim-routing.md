# CP-013 — NVIDIA NIM cloud model routing (local ↔ cloud)

> Status: done
> Depends on: CP-002, CP-004, CP-007
> Phase: 4 Stretch (scoring boosters)

## Objective
Add a model router so the Art Director's reasoning can run on **local Nemotron (Ollama)**
by default but fail over to **NVIDIA NIM cloud** (`integrate.api.nvidia.com`) when Ollama
is unavailable/overloaded. Demonstrates NemoClaw-style routed inference and broadens
NVIDIA SDK utilization (rubric 4) + resilience (rubric 3).

## Scope
- `src/common/router.py` — `async def reason(messages, **kw)` that picks backend:
  - try local Ollama; on unavailable/timeout/OOM → fall back to `NimClient` (CP-002).
  - record the routing decision in `orchestrator_log.json` (`backend: local|nim`, reason).
- Wire the Art Director (CP-004) to call `router.reason` instead of `OllamaClient` directly.
- Model Orchestrator (CP-007) hook: `on_ollama_unavailable` → switch to NIM for the rest
  of the run (sticky) and log.
- Config flag `ROUTING_STRATEGY` (`local-first` default | `cloud-first` | `local-only`).
- `docs/deployment.md` section on routed inference + when cloud is used.

## Non-goals
- No routing for the VLM (Stepfun is always cloud for vision).
- No NIM container locally (that's CP-014's territory) — this is the cloud NIM endpoint.
- No fine-tuning (CP-014).

## Constraints
- Cloud routing must be opt-in via config; default `local-first` preserves the
  "local compute" emphasis the hackathon requires.
- Never send the reference image to NIM (text reasoning only); images stay with Stepfun.
- Log every routing decision for the evidence trail.

## Acceptance tests
- [x] `pytest tests/test_router.py` — local ok → uses Ollama; local down → uses NIM; decision logged.
- [x] `ROUTING_STRATEGY=local-only` never calls NIM even when local is down (fails loud).
- [x] Art Director reasoning routed via `router.reason` end-to-end in a mocked pipeline (runner wires `ReasonRouter` into `plan`/`rewrite`; `test_runner.py` still green).
- [x] `orchestrator_log.json` contains a `backend` field on reasoning events (`OrchestratorEvent.backend` + `record_routing`).
- [x] Live smoke: dead Ollama → a reasoning call completes via NIM (`tools/smoke_router.py`: real `nvidia/llama-3.3-nemotron-super-49b-v1.5`, 158-char answer extracted from `reasoning_content`, sticky backend=nim, 11.4 s).
- [x] `make lint && make typecheck` pass.

## Relevant context
- Design refs: `03-model-optimization.md` (O6 local↔cloud routing), `01-agents.md` (Art Director model).
- Uses `NVIDIA_API_KEY` + `NVIDIA_NIM_BASE_URL` from `.env` (already present).
- Emphasize in docs that this is *failover*, not the default path, to keep the "local compute" narrative intact.
- **NIM Nemotron reasoning quirk (verified CP-002):** `nvidia/llama-3.3-nemotron-super-49b-v1.5`
  is a reasoning model — `message.content` is `null` and the answer is in
  `message.reasoning_content` (mirrors the local Ollama `think` quirk). The router must
  extract from `reasoning_content` when `content` is empty, OR use a non-reasoning Nemotron
  variant (e.g. `nvidia/llama-3.1-nemotron-nano-8b-v1`) for short structured outputs, and
  budget enough `max_tokens` for the reasoning trace to complete. Validated live: a 200 OK
  with `content=None` is a *transport* success, not a failure.
