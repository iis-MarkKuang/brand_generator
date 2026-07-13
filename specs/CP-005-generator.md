# CP-005 — Generator agent (ComfyUI FLUX + PuLID)

> Status: ready
> Depends on: CP-001, CP-002
> Phase: 1 Core agents

## Objective
Implement the Generator: run a parameterized ComfyUI FLUX+PuLID workflow per
`AssetSpec` and produce a PNG (+ render metadata). This is the local image-generation
stage that the Model Orchestrator schedules VRAM around.

## Scope
- `src/comfyui/brand_workflow.json` — derived from the workshop `face_workflow.json`,
  parameterized (see `04-comfyui-workflow.md` node graph).
- `src/agents/generator.py` — `async def generate_asset(asset_spec, run_dir, attempt) -> RenderResult`.
  - Load workflow JSON; if `uses_pulid` false, prune PuLID nodes (2–6) and rewire
    KSampler `model` input to the raw CheckpointLoader.
  - Substitute prompt/negative/size/seed/steps/filename.
  - Submit via `ComfyUIClient`, poll, fetch PNG, save to
    `runs/<run_id>/assets/<asset_id>__v<attempt>.png`.
  - Write `render_meta.json` (seed, steps, cfg, latency_s, vram snapshot).
  - Emit `MEDIA:<abs_path>` line (used later by the OpenClaw skill).
- CUDA-dirty auto-recovery: on `CUDA error: invalid argument` / `illegal memory access`,
  call `scripts/comfyui-ctl.sh restart` (workshop script), wait for `:8200` health, retry once.

## Non-goals
- No VRAM swapping logic here — call into the Model Orchestrator (CP-007) before rendering.
- No critique (CP-006), no loop (CP-008).
- No LoRA fine-tuning (CP-014) — use base FLUX weights.

## Constraints
- Longest side ≤ 1344; steps default 24, 18 on retry (passed by caller).
- One render at a time (ComfyUI is single-flight on GB10) — enforce via a module-level lock.
- Timeout `max_wait_s=180`; on timeout kill the prompt and retry once.
- Workflow JSON must stay API-format compatible with the workshop ComfyUI bundle.

## Acceptance tests
- [ ] `pytest tests/test_generator.py` — mocked ComfyUI returns a PNG; `generate_asset` writes the file + `render_meta.json` and returns a `RenderResult` with the abs path.
- [ ] PuLID-prune path: an `AssetSpec` with `uses_pulid=false` yields a workflow dict with no PuLID nodes and KSampler wired to the raw model.
- [ ] CUDA-dirty path: mocked error triggers exactly one restart + one retry.
- [ ] Live smoke (manual, on Spark): a `logo` AssetSpec renders a 1024² PNG in < 90s with `--fast` mode.
- [ ] `make lint && make typecheck` pass.

## Relevant context
- Design refs: `04-comfyui-workflow.md` (node graph, dynamic fields, asset defaults), `03-model-optimization.md` (O2 FP8 fast mode, step trade-off).
- Reference workflow: the workshop `face_workflow.json` (notebook §4.3) — reuse exact node class names and safetensors filenames.
- Workshop recovery pattern: notebook §5.1 already implements the CUDA-dirty restart; mirror it.
