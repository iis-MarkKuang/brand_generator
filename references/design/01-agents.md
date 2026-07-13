# 01 — Agent Specifications

> Detailed spec for each agent: inputs, outputs, model, prompt contract, failure modes.
> The Art Director is the **delegating** agent; the others are its tools.

## Agent topology

```
                 ┌──────────────────────────────────────────────┐
                 │  Art Director  (Nemotron-3-Super, local)     │
                 │  — holds run state, plans, decides retries   │
                 │  — tool-calling agent                        │
                 └──────────────────────────────────────────────┘
        ┌──────────────┬───────────────────┬─────────────────────┐
        │              │                   │                     │
        ▼              ▼                   ▼                     ▼
  Brand Analyst   Generator           Critic               Model Orchestrator
  (tool)          (tool)              (tool)               (tool)
  Stepfun VLM     ComfyUI FLUX+PuLID  Stepfun VLM          local scheduler
```

The Art Director is implemented as a tool-calling loop: it receives the user request,
calls `analyze_brand`, then plans, then repeatedly calls `generate_asset` + `critic_asset`,
rewriting prompts on failure, until all assets pass. The Model Orchestrator is called
implicitly before/after any generation or reasoning step.

---

## Agent 1 — Brand Analyst

- **Model:** Stepfun `step-3.7-flash` (VLM), `reasoning_effort: high`.
- **Inputs:** `brief: str`, `reference_image: path|url`, `brand_name: str`.
- **Output:** `brand_dna.json` (schema in `02-data-contracts.md`).
- **Prompt contract:** "You are a senior brand strategist. Analyze the reference image
  and the brief. Return STRICT JSON with: palette (5 hex colors ranked primary→accent),
  mood (5 keywords), typography_class (serif|sans|display|mono), typography_pairs,
  visual_keywords (8), dos (list), donts (list), personality (one paragraph)."
- **Tool-calling:** none — pure VLM extraction.
- **Failure modes:** non-JSON output (retry with repair prompt), missing fields
  (validate against schema, re-prompt for missing fields only).
- **Caching:** keyed by `hash(brief + image)`; cached to `runs/<run_id>/brand_dna.json`
  and a global `cache/brand_dna/<hash>.json`.

## Agent 2 — Art Director (delegating)

- **Model:** NVIDIA Nemotron-3-Super 120B via Ollama (`think: false` to keep content
  populated, per workshop quirk), OR NVIDIA NIM cloud when routed (CP-013).
- **Inputs:** `brand_dna.json`.
- **Output:** `asset_manifest.json` (list of `AssetSpec`).
- **Tools exposed to it:**
  - `analyze_brand(brief, image) -> BrandDna`
  - `generate_asset(asset_spec) -> png_path`
  - `critic_asset(png_path, asset_spec, brand_dna) -> CriticResult`
  - `rewrite_prompt(asset_spec, critic_feedback) -> AssetSpec`
  - `request_vram(target: "ollama"|"comfyui") -> ok` (delegates to Model Orchestrator)
- **Prompt contract:** system prompt establishes it as an art director that produces a
  *coherent* asset set (shared palette/type/mood across all assets), not independent
  images. Emphasizes cross-asset consistency in the plan.
- **Loop:** bounded `max_retries` per asset (default 2); on hard fail after retries,
  mark asset `failed` and continue (partial-kit resilience).
- **Failure modes:** Ollama timeout → fall back to NIM cloud (CP-013); VRAM OOM →
  trigger Model Orchestrator swap and retry.

## Agent 3 — Generator

- **Model/engine:** ComfyUI FLUX.1-dev (fp8) + PuLID + InsightFace, Blackwell `--fast`.
- **Inputs:** `AssetSpec` (prompt, composition, size, seed, `uses_pulid`, optional
  `pulid_reference` path for mascot/face identity).
- **Output:** PNG file + `MEDIA:<abs_path>` line + a `render_meta.json`
  (seed, steps, cfg, latency_s, vram_used_gb).
- **Workflow:** `brand_workflow.json` (see `04-comfyui-workflow.md`); the runner
  substitutes the prompt, seed, size, and optional PuLID reference, then POSTs to
  ComfyUI's `/prompt` API and polls `/history/{prompt_id}`.
- **Failure modes:** CUDA context dirty (workshop-documented) → auto-restart ComfyUI
  via `comfyui-ctl.sh restart` then retry once; workflow rejected → return structured
  error to Art Director.

## Agent 4 — Critic

- **Model:** Stepfun `step-3.7-flash` (VLM), `reasoning_effort: low` for fast
  re-checks (raised to `medium` only on a borderline first pass).
- **Inputs:** `png_path`, `AssetSpec`, `BrandDna`.
- **Output:** `CriticResult` (`{pass: bool, score: 0-100, palette_match, mood_match,
  legibility, on_brand, feedback: str}`).
- **Prompt contract:** "Score this asset against the brand DNA. Be strict on palette
  (hex distance) and legibility. Return STRICT JSON. pass=false if score<70."
- **Failure modes:** non-JSON → repair prompt; false-negative loop (Art Director
  detects repeated identical fails) → accept with caveat and log.

## Agent 5 — Model Orchestrator (the optimization agent)

- **Engine:** local Python scheduler (no LLM needed for the core loop; optional
  Nemotron planner for adaptive policy in CP-007 stretch).
- **Inputs:** target stage (`reason` | `generate` | `idle`), VRAM snapshot.
- **Outputs:** swap commands + `orchestrator_log.json` (decisions, VRAM before/after,
  latency).
- **Responsibilities:**
  1. Before generation: `ollama stop <reasoning_model>` → wait until VRAM frees →
     greenlight ComfyUI.
  2. After generation: `ollama run` preload Nemotron if next step needs reasoning.
  3. Pick `reasoning_effort` for VLM calls (high for analysis, low for re-checks).
  4. Enforce cache hits to skip re-analysis.
  5. Emit the evidence trail used by the docs' optimization section.
- **Failure modes:** `ollama stop` hangs → SIGTERM then SIGKILL after timeout; if
  ComfyUI still OOMs, drop to a smaller generation size and retry.

## Agent 6 — Assembler

- **Engine:** local Python (no LLM).
- **Inputs:** approved asset PNGs + `AssetSpec`s + `BrandDna`.
- **Output:** `brand_kit/` directory: renamed assets (`logo.png`, `hero_banner.png`,
  `social_square.png`, `product_mockup.png`, `business_card.png`), `brand_guide.md`
  (palette swatches in markdown, typography, usage dos/don'ts, asset list), and
  `kit_manifest.json` (the contract the Gallery reads).
- **Failure modes:** missing asset → write a placeholder + mark `status: failed` in
  manifest so the Gallery can show a graceful "generation failed" tile.

---

## Inter-agent data flow (files)

```
runs/<run_id>/
├── input.json                 # brief, reference image path, brand_name
├── brand_dna.json             # Brand Analyst output
├── asset_manifest.json        # Art Director output
├── assets/
│   ├── logo__v1.png           # attempt naming: <asset>__v<n>.png
│   ├── logo__v2.png
│   ├── critic__logo__v1.json  # CriticResult per attempt
│   └── ...
├── orchestrator_log.json      # Model Orchestrator decisions
├── run.log                    # every agent call, latency, tokens
└── brand_kit/
    ├── logo.png
    ├── hero_banner.png
    ├── social_square.png
    ├── product_mockup.png
    ├── business_card.png
    ├── brand_guide.md
    └── kit_manifest.json
```
