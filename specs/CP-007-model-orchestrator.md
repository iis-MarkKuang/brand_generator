# CP-007 — Model Orchestrator (GPU VRAM scheduler)

> Status: done
> Depends on: CP-001, CP-002
> Phase: 1 Core agents

## Objective
Implement the Model Orchestrator agent — the optimization centerpiece. It owns the
Ollama↔ComfyUI VRAM swap state machine and the VLM effort-routing/cache policy, and
emits the evidence trail (`orchestrator_log.json`) that the docs/demo cite for rubric 2.

## Scope
- `src/optimizer/model_orchestrator.py`:
  - `async def request_vram(target: "ollama"|"comfyui") -> Ok` — predictive swap.
    `ollama stop <model>`, poll `nvidia-smi` until VRAM < threshold, confirm ComfyUI health.
    Reload Ollama when reasoning is next.
  - State machine: `IDLE → REASONING → GENERATING → ...` driven by Art Director's
    declared `next_stage` (CP-008) so swaps overlap with network-bound VLM calls.
  - `effort_for(stage, attempt)` → VLM `reasoning_effort` (high/medium/low per O3).
  - `cache_key(brief, image)` + cache lookup used by Brand Analyst (CP-003 calls in).
  - `record(event)` → append to `runs/<run_id>/orchestrator_log.json` with VRAM
    before/after + latency.
- `src/common/vram.py` — `nvidia-smi` parsing helpers (free/used VRAM).
- Predictive pre-swap: when the Art Director signals `next_stage="generate"`, unload
  Ollama during the preceding critic call.

## Non-goals
- No NIM cloud routing logic (CP-013) — but expose a hook `on_ollama_unavailable`.
- No adaptive LLM policy (rule-based state machine is enough for the hackathon).
- No LoRA (CP-014).

## Constraints
- `ollama stop` must have a hard timeout; SIGTERM then SIGKILL if it hangs.
- Never unload Ollama while a reasoning call is in flight (track in-flight count).
- All decisions logged with timestamps for the evidence trail.
- If ComfyUI still OOMs after swap, drop size by 128px and retry (degraded, logged).

## Acceptance tests
- [ ] `pytest tests/test_model_orchestrator.py` — mocked Ollama + nvidia-smi: `request_vram("comfyui")` unloads Ollama, waits for VRAM threshold, returns ok; reload path symmetric.
- [ ] In-flight guard: a reasoning call in progress blocks unload (assert no `stop` issued).
- [ ] `orchestrator_log.json` records events with `vram_before_gb`/`vram_after_gb`/`latency_s`.
- [ ] `effort_for("analyze")=="high"`, `effort_for("critic", attempt=2)=="low"`.
- [ ] Live smoke (manual, on Spark): a real swap cycle frees ~80 GB VRAM and reloads within ~10s; logged.
- [ ] `make lint && make typecheck` pass.

## Relevant context
- Design refs: `03-model-optimization.md` (O1 state machine, O3 effort routing, O4 caching), `01-agents.md` (Agent 5).
- Workshop fact: GB10 is a Grace-Blackwell **iGPU with ~120 GiB unified memory** (shared
  CPU+GPU pool; `nvidia-smi` reports `[N/A]`). A resident Nemotron and FLUX cannot both
  hold large chunks of that pool — the bundle serves Ollama with `OLLAMA_KEEP_ALIVE=5s`
  so an idle model frees memory within 5 s. Dev model: `nemotron-3-nano:30b`; demo:
  `nemotron-3-super:120b` (≈86 GB on disk).
- This is the single most important packet for the 25% "model optimization depth" score; the demo must surface `orchestrator_log.json` live.
