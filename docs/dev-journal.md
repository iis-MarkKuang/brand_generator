# Development journal — "Ten-Day Talk" (scoring criterion 6, 5%)

Record the day-by-day development journey of StyleForge for the DGX Spark Hackathon.

## Day 1 — Ideation & architecture
- Parsed hackathon requirements & judging rubric → `docs/hackathon-requirements.md`.
- Surveyed the DGX Spark workshop stack: Ollama (Nemotron-3-Super 120B, qwen3.6),
  ComfyUI (FLUX + PuLID), OpenClaw agent platform, NemoClaw sandboxing.
- Confirmed Stepfun `step-3.7-flash` as the VLM (native image understanding, tool
  calling, OpenAI-compatible API).
- Chose **StyleForge**: multi-agent brand identity studio. Locked architecture in
  `docs/architecture.md`.

## Day 1 (cont.) — Credentials & repo setup
- Collected third-party keys, all stored in gitignored `.env` (template in `.env.example`):
  - **Stepfun** `step-3.7-flash` VLM (Brand Analyst + Critic) — required.
  - **NVIDIA build.nvidia.com** API key — enables local-vs-cloud NIM model routing demo.
  - **Hugging Face** token — for the NeMo LoRA fine-tuning optimization leg.
  - **Telegram** bot token — NemoClaw always-on remote access demo.
- Initialized git repo (`master`, unborn). Verified `.env` is ignored (`.gitignore` line 2).
- GitHub/Gitee push deferred; local repo ready for branching/committing.

## Day 2 — Architecture design & coding-agent harness
- Wrote the authoritative design in `references/design/` (7 docs):
  00-overview, 01-agents, 02-data-contracts, 03-model-optimization,
  04-comfyui-workflow, 05-frontend, 06-deployment.
- Set up the coding-agent harness: `AGENTS.md`, 5 `.cursor/rules/*.mdc`
  (architecture, change-packet-workflow, secrets, python-style, frontend-style),
  and `tools/` scripts (`new-change-packet.sh`, `validate-env.sh`, `check-secrets.sh`).
- Verified `check-secrets.sh` passes clean and detects a planted secret;
  `validate-env.sh` passes against the real `.env`.
- Decomposed the project into **16 change packets** (`specs/CP-001..CP-016`), each with
  objective / scope / non-goals / constraints / acceptance tests / relevant context.
- Updated `ROADMAP.md` with phases, dependency graph, critical path, and stretch path.

## Day 2 (cont.) — Architecture/roadmap review & CP-001
- Review pass found: drift (6→7 optimization points), security loopholes (path traversal,
  CORS wildcard, upload DoS, Telegram unauthorized GPU drain, secrets-in-sandbox), and
  token-explosion risks (unbounded VLM/render calls, image accumulation in director
  context, full re-plans). Added `references/design/07-security-and-tokens.md` +
  `.cursor/rules/security.mdc`; reconciled `docs/architecture.md`; updated affected CPs.
- Key change: single secrets boundary — only the FastAPI orchestrator loads `.env`;
  OpenClaw skill & NemoClaw sandbox call it over `localhost:8000`. Moved CP-009 to
  depend on CP-010.
- Environment: this dev box has no PyPI access; using the Tsinghua mirror
  (`UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple/`) for `uv`. uv 0.11.28 installed.
- **CP-001 implemented:** `pyproject.toml` (uv, ruff, mypy, pytest), `src/common/`
  (`config.py` pydantic-settings, `schemas.py` mirroring `02-data-contracts.md` with
  token-hygiene + run-id guards, `logging.py` structlog w/ secret sanitization,
  `runs.py` traversal-safe RunDir), `Makefile`, `tests/test_schemas.py` (11 tests).
- Acceptance green: `make lint`, `make typecheck` (mypy strict, 0 issues), `make test`
  (11 passed), `make check-secrets`, `make validate-env`.

## Day 2 (cont.) — Local stack bring-up on the Spark
- Discovered the **workshop bundle is present** at
  `/home/Developer/build_a_claw_workshop-bundle/` (121 GB: Ollama+GB10 CUDA libs,
  ComfyUI+venv, hf-cache with FLUX/PuLID/InsightFace, OpenClaw, scripts). Not at the
  notebook's `/home/nvidia/...` path — updated `.env` `OPENCLAW_HOME` accordingly.
- **GPU works via the bundle Ollama**: detected `CUDA / NVIDIA GB10 / iGPU /
  total 119.7 GiB / available 111.9 GiB`. Key finding: the GB10 is a Grace-Blackwell
  **integrated GPU with ~120 GiB unified memory** (not discrete VRAM — that's why
  `nvidia-smi` reports `[N/A]`). Updated `docs/architecture.md`, `03-model-optimization.md`,
  `06-deployment.md`, `CP-007`, `hackathon-requirements.md` to reflect unified memory
  (was: "86 GB discrete VRAM"). The VRAM-scheduling story still holds; the bundle's
  `OLLAMA_KEEP_ALIVE=5s` is the swap mechanism.
- System `/usr/bin/ollama` failed to detect CUDA (CPU-only); the bundle's
  `ollama/bin/ollama` (cuda_v13 libs) works. Started both services via the bundle's
  `ollama-ctl.sh` / `comfyui-ctl.sh`.
- Network: PyPI blocked → using Tsinghua mirror for uv; HuggingFace blocked but
  `hf-mirror.com` reachable (not needed — bundle ships hf-cache); GitHub blocked but
  gitee/ghfast.top reachable; Stepfun API + NVIDIA NIM cloud both reachable.
- Models: bundle ships `qwen3.6:35b`; pulling `nemotron-3-nano:30b` from the Ollama
  registry for the dev Art Director (demo will use `nemotron-3-super:120b`).
- **Services up:** Ollama :11434 (GPU), ComfyUI :8200 (`--fast`, FLUX+PuLID).
- Flagged: the bundle dir contains an `xmrig` miner (not part of the workshop) —
  awareness only, left untouched.
- Commits pending: no git identity configured on this box (config not modified per
  harness rules); awaiting user name/email for the split commit (baseline on `master`,
  CP-001 on its branch).

## Day 2 (cont.) — CP-002 inference clients
- Implemented four typed async clients behind the single secrets boundary:
  `src/common/stepfun.py` (`StepfunClient` + `image_to_data_url`/`bytes_to_data_url`/
  `resize_for_vlm`), `src/common/ollama.py` (`chat`/`stop`/`ps`/`vram_probe`),
  `src/common/comfyui.py` (`submit`/`wait`/`fetch_image`/`health`),
  `src/common/nvidia_nim.py` (`NimClient`). Shared `src/common/_http.py`
  (`retry_transient` on 5xx/timeout) and `src/common/exceptions.py`.
- `chat_vlm` injects `image_url.detail` tiers and does one JSON-repair retry (token
  budget T3). `resize_for_vlm` pre-downscales to ≤1024px. Clients log model + latency +
  token/step counts, never image bytes.
- **Unit tests:** `tests/test_{stepfun,ollama,comfyui}_client.py` via `httpx.MockTransport`
  + `tests/conftest.py` `fake_settings` (no real secrets). 24 tests pass.
  `make lint` (ruff), `make typecheck` (mypy strict, 0 issues) green.
- **Live smoke** (`tools/smoke_inference_clients.py`) all green on the Spark:
  - Stepfun VLM `step-3.7-flash` parsed `{"dominant_color":"#d7262c"}` from a red square.
  - Ollama `qwen3.6:35b` on the GB10 → `"ok"` (8.6s incl. load, `think=false`).
  - ComfyUI `/api/system_stats` → healthy.
  - NIM `nvidia/llama-3.3-nemotron-super-49b-v1.5` → 200 OK.
- **NIM reasoning quirk found & recorded in CP-013:** Nemotron is a reasoning model —
  `message.content` is `null` with the answer in `message.reasoning_content` (mirrors the
  local `think` quirk). CP-002 transport is correct; CP-013 must extract from
  `reasoning_content` or use `nvidia/llama-3.1-nemotron-nano-8b-v1` for short structured
  output. Fixed a stale `.env`/config NIM model id (`nvidia/nemotron-3-super` →
  `nvidia/llama-3.3-nemotron-super-49b-v1.5`) in `.env`, `.env.example`, `config.py`,
  and pinned it in `03-model-optimization.md` O6.
- `nemotron-3-nano:30b` (dev Art Director) pulling from the Ollama registry (~24 GB,
  ~30% done). Services left running for subsequent CPs.

## Day 2 (cont.) — CP-003 Brand Analyst agent
- `src/agents/brand_analyst.py`: `analyze_brand(brief, image, brand_name, *, run_dir,
  settings, client, cache_dir) -> BrandDna`. System prompt in
  `src/agents/prompts/analyst.md` (strict-JSON contract for the exact `BrandDna` fields).
- Flow: resize image → data URL → Stepfun `chat_vlm` (`reasoning_effort=high`,
  `image_detail=high`) → validate `BrandDna`; on schema failure, one repair retry that
  feeds back the validation errors, then raise. `brand_name` enforced from the caller.
- **Caching (O4):** key = `sha1(brief + image_bytes)` → `cache/brand_dna/<hash>.json`;
  cache hit skips the VLM entirely but still writes `runs/<run_id>/brand_dna.json`.
- `.gitignore` now excludes `runs/` and `cache/` (runtime artifacts).
- **Unit tests** (`tests/test_brand_analyst.py`, mocked VLM): valid-JSON path,
  schema-repair path (2 calls), cache-hit path (assert VLM not called). 27 tests pass;
  `make lint` + `make typecheck` (mypy, 14 files) green.
- **Live smoke** (`tools/smoke_brand_analyst.py`, real Stepfun on
  `sample/sample_face.jpg`): produced a coherent personal-brand DNA — palette
  `[Obsidian #0D0D0F, Nova Teal #00D4AA, Pure White #FFFFFF, Cloud Gray #F2F2F7,
  Cool Gray #8E8E93]`, mood `[approachable, technical, energetic, modern, reliable]`,
  `typography_class=sans`, 8 visual keywords; written to
  `runs/20260713-035802-82447/brand_dna.json`. ~25 s end-to-end.
- CP-003 acceptance: all 6 criteria green.

## Day 2 (cont.) — CP-004 Art Director agent
- `src/agents/art_director.py`: `plan_assets(brand_dna, asset_types, *, run_dir,
  base_seed, settings, client, cache_dir) -> AssetManifest` and
  `rewrite_prompt(asset_spec, critic_feedback, ...) -> AssetSpec`; plus
  `DIRECTOR_TOOLS` schemas (analyze_brand/generate_asset/critic_asset/request_vram)
  for the CP-008 tool-calling loop. System prompt in `prompts/director.md` enforcing
  cross-asset consistency, ≥2 palette hex tokens per flux_prompt, negative_prompt on
  every asset, size ≤1344, `uses_pulid` only for mascot/identity.
- Runs on the local Ollama reasoning model with `think=False` (workshop quirk).
  Deterministic seeds per `(base_seed, brand_dna_hash, asset_id)` for reproducible
  renders. Planning cached per `(brand_dna_hash, asset_types)` (T9); id/seed enforced
  by the runtime (model told not to emit them). `plan_assets` re-stamps `run_id` from
  the cache so a cached plan serves any new run.
- **Unit tests** (`tests/test_art_director.py`, mocked Ollama): valid plan, reproducible
  seeds (two model-path calls → identical seeds), repair path, cache-hit (Ollama not
  called), rewrite_prompt (feedback sent to model + incorporated). 32 tests pass;
  ruff + mypy (15 files) green.
- **Live smoke** (`tools/smoke_art_director.py`) used `qwen3.6:35b` as the reasoning
  model (nano still pulling — flaky registry parts, auto-retrying) per the agreed
  stand-in: produced a coherent 5-asset kit (logo/hero_banner/social_square/
  product_mockup/business_card) reusing the Nova Lin palette hex tokens across all
  assets, deterministic seeds, written to `runs/20260713-040820-00855/asset_manifest.json`,
  ~26 s. Will re-run on `nemotron-3-nano:30b` once the pull completes.
- CP-004 acceptance: all 5 criteria green.

## Day 2 (cont.) — CP-005 Generator agent (ComfyUI FLUX + PuLID)
- `src/comfyui/brand_workflow.json`: API-format graph derived from the workshop's
  `superhero_face_api.json` (13 nodes: CheckpointLoaderSimple→flux1-dev-fp8,
  PulidFlux* 2-6, CLIPTextEncode 7/8, FluxGuidance 9 guidance=3.5,
  EmptySD3LatentImage 10, KSampler 11 cfg=1.0 euler/simple, VAEDecode 12, SaveImage 13).
- `src/agents/generator.py`: `generate_asset(asset_spec, run_dir, attempt, ...) ->
  RenderResult`. `build_workflow()` substitutes prompt/negative/size/seed/steps/filename
  and **prunes PuLID nodes 2-6 + rewires KSampler model to [1,0]** when `uses_pulid=false`.
  Single-flight (`asyncio.Lock`) on the GB10; CUDA-dirty auto-recovery
  (`CudaDirtyError` on "CUDA error"/"illegal memory access"/"invalid argument" →
  `comfyui-ctl.sh restart` → wait health → retry once). Non-recoverable errors return a
  `RenderResult(error=...)` so the loop can mark the asset failed and continue.
  Emits `MEDIA:<abs_path>`; writes `render_meta__<id>__v<attempt>.json`; vram snapshot
  from `/proc/meminfo MemAvailable` (unified-memory proxy).
- `RenderResult` + `CudaDirtyError` added to schemas/exceptions; `comfyui_ctl_script`
  setting added (set in `.env` to the bundle script).
- **Unit tests** (`tests/test_generator.py`, mocked ComfyUI): valid render (PNG +
  render_meta written), PuLID-prune (no nodes 2-6, KSampler→[1,0]) and PuLID-keep paths,
  CUDA-dirty (exactly one restart + one retry, final PNG written), non-CUDA error →
  error result. 37 tests pass; ruff + mypy (17 files) green.
- **Live smoke** (`tools/smoke_generator.py`): real FLUX fp8 render of a 1024² logo →
  568 KB PNG in **31.1 s** (< 90 s target), `MEDIA:` emitted, `vram_free_mib=97720`
  (~95 GB free). The render faithfully reproduced the brand brief — "Ember & Oat"
  hand-drawn script wordmark in espresso #3B2417 on oat-cream #F3E9D8 with a coffee-bean
  motif, matching the palette hex tokens in the prompt.
- CP-005 acceptance: all 5 criteria green.

## Day 2 (cont.) — CP-006 Critic agent (Stepfun VLM)
- `src/agents/critic.py`: `critic_asset(png_path, asset_spec, brand_dna, *, run_dir,
  attempt, settings, client) -> CriticResult`. System prompt in `prompts/critic.md`
  (strict-JSON, 0-100 score + palette_match/mood_match/legibility/on_brand + <60-word
  actionable feedback; pass derived as `score >= critic_pass_threshold`).
- **Effort/detail routing (T2/T3):** first attempt `reasoning_effort=medium`,
  `image_detail=high`; re-checks (`attempt >= 2`) `low`/`low` (from
  `vlm_image_detail_first`/`recheck` settings). Image pre-resized to ≤1024px.
- **Resilience:** one repair retry on parse/schema failure, then a structured
  `critic_failed` `CriticResult` (pass=false, score=0) — never crashes the run.
  `feedback` forced non-empty when `pass=false` (fallback copy). Writes
  `runs/<run_id>/assets/critic__<id>__v<attempt>.json` (with the `pass` JSON alias).
- `critic_pass_threshold` setting added (default 70).
- **Unit tests** (`tests/test_critic.py`, mocked VLM): pass boundary (69/70), re-check
  uses `detail=low` (asserted on request), repair path, feedback-non-empty-when-fail,
  structured-failure-never-crashes. 42 tests pass; ruff + mypy (18 files) green.
- **Live smoke** (`tools/smoke_critic.py`): real Stepfun VLM on the CP-005 logo →
  **score 94, pass=true**, all sub-scores 0.95; feedback correctly verified the
  #F3E9D8/#3B2417 palette and the craft mood, with a concrete small-scale legibility
  fix. Written to `runs/20260713-084812-92349/assets/critic__logo__v1.json`, ~21 s.
- CP-006 acceptance: all 6 criteria green.

## Day 2 (cont.) — CP-007 Model Orchestrator (GB10 unified-memory scheduler)
- `src/common/vram.py`: `free_vram_mib`/`free_vram_gb` from `/proc/meminfo MemAvailable`
  (GB10 iGPU unified pool — `nvidia-smi` reports `[N/A]`). Generator refactored to use it.
- `src/optimizer/model_orchestrator.py`: `ModelOrchestrator` owning the Ollama↔ComfyUI swap
  state machine (`Stage` IDLE/REASONING/GENERATING). `request_vram("comfyui")` →
  `ollama.stop(model)` (if no reasoning in flight) + poll `free_vram_gb` to
  `vram_free_threshold_gb` + confirm ComfyUI health; `request_vram("ollama")` → best-effort
  free ComfyUI + transition. **In-flight guard:** `begin/end_reasoning` refcount blocks
  unload while a reasoning call is active. `effort_for(stage, attempt)` → VLM effort
  (analyze/plan=high, critic=medium→low). `cache_key` = Brand-DNA O4 key. Every swap
  appends an `OrchestratorEvent` (vram_before/after + latency) to
  `runs/<id>/orchestrator_log.json` — the rubric-2 evidence trail.
- Settings added: `vram_free_threshold_gb=32`, `ollama_unload_timeout_s=30`.
- **Unit tests** (`tests/test_model_orchestrator.py`, mocked Ollama/ComfyUI/vram):
  comfyui-unloads-ollama, ollama-transitions-no-stop + free-comfyui, in-flight guard
  (no stop issued), orchestrator_log records events, `effort_for` routing, `cache_key`
  stable. 50 tests pass; ruff + mypy (20 files) green.
- **Live smoke** (`tools/smoke_model_orchestrator.py`): warm `nemotron-3-nano:30b` →
  `request_vram("comfyui")` → **ok=True, unloaded=True, state=generating**, event logged
  to `orchestrator_log.json` in ~0.05 s. Resident VRAM delta was ~0 because the bundle's
  `OLLAMA_KEEP_ALIVE=5s` auto-frees nano quickly and nano is only 24 GB; the dramatic
  ~80 GB freed-delta is a demo target with `nemotron-3-super:120b` (86 GB). The swap
  mechanism, in-flight guard, and evidence trail are verified.
- Also: restarted Ollama (it had stopped) — `nemotron-3-nano:30b` now registered alongside
  `qwen3.6:35b`; restarted ComfyUI (it had exited after the CP-005 render).
- CP-007 acceptance: unit + live-smoke mechanism green (the ~80 GB delta is deferred to
  the super-model demo).

## Day 2 (cont.) — CP-008 Master orchestrator loop + Assembler
- `src/orchestrator/runner.py`: `run_pipeline(run_input) -> KitManifest` wires the agents
  end-to-end — analyze_brand → plan_assets → per-asset (request_vram("comfyui") →
  generate_asset → critic_asset → rewrite_prompt on fail) → assemble_kit. All agent
  functions are injectable for testing.
- **Caps & resilience (T1/T5/T6/T8):** `MAX_TOTAL_VLM_CALLS`/`MAX_TOTAL_RENDERS`/
  `RUN_TIMEOUT_S` checked per-asset; on bail (cancel/timeout/cap) the remaining assets are
  recorded as `failed` (status `partial`) — a single asset failure never aborts the run.
  Per-asset `rewrite_prompt` only (never re-plans the manifest). Cooperative cancellation
  via an `asyncio.Event`. Director stays text-only (no images fed to Ollama).
- `src/agents/assembler.py`: `assemble_kit` copies approved renders to `brand_kit/<id>.png`,
  writes `brand_guide.md` (palette hex table, typography, mood, do/don't, asset list,
  personality), emits validated `kit_manifest.json` with `optimization_stats`
  (vram_swaps, brand_dna_cache_hit, critic effort counts, total_vlm_calls/renders,
  routing counts) drawn from the orchestrator evidence trail.
- `runs_root` setting added (default `runs`); provenance reference image copied into the
  run's input dir.
- **Unit tests** (`tests/test_runner.py`, fully mocked): 2-approved-1-failed partial kit
  (brand guide has all hex + asset list; manifest validates with optimization_stats),
  VLM-cap no-runaway, timeout partial, cancellation, manifest round-trip. 55 tests pass;
  ruff + mypy (23 files) green.
- **Golden E2E** (`tools/run_pipeline.py`): real run on `sample_face.jpg` with
  `nemotron-3-nano:30b` (reasoning) + `step-3.7-flash` (VLM) + ComfyUI FLUX (generator).
  2 assets (logo, social_square), max_retries=1 → **350 s, 7 vram swaps, 5 VLM calls,
  4 renders**, status `partial` (scores 62/65, below the strict 70 threshold). The critic
  did real brand QA — caught FLUX's garbled wordmark ("BROASTED"→"ROASTED"), missing
  `#C65D3B` ember accent, and cool-tone leakage, with concrete hex/legibility fixes.
  nano:30b successfully drove plan + prompt-rewrite (one auto-repair on a >600-char
  prompt). Artifacts recorded under `tests/golden/`. Complete kits are achievable by
  tuning `critic_pass_threshold`, selecting text-light assets, or raising retries — the
  pipeline, swap scheduler, bounded loop, and partial-kit resilience are all verified.
- CP-008 acceptance: all green (unit + golden E2E; complete-kit is a tuning lever, not a
  correctness gap).
