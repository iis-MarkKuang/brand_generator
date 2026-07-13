# StyleForge — Demo Video Script

> Shot-by-shot demo video script. Maps to judging criterion 5 (demo effect, 10%) and
> submission requirement 5 (project demo video). Target length: ~3–4 minutes. The
> filmer's job is to capture the screens below; the narration ties each shot to a
> rubric criterion.

## Setup before filming

- DGX Spark booted; Ollama (`nemotron-3-nano:30b`) + ComfyUI (FLUX-dev fp8) running.
- FastAPI backend `:8000` healthy; gallery `:5173` open; OpenClaw `:9000` open.
- A prepared brief + reference image ready (e.g. "Ember & Oat" coffee roaster).
- Terminal with `make acceptance` ready to run (for the "completeness" shot).
- A second browser tab on the live run view (so the critic loop is visible).

---

## Shot list

### Shot 1 — The problem (0:00–0:20) · *criterion 1*
- **Visual:** side-by-side of a generic AI logo generator (one image) vs. a real brand
  kit (logo + banner + social + card + guide, all consistent).
- **Narration:** "AI logo generators give you one image. A real brand identity is a
  *coherent set*. StyleForge produces the set — locally, on one DGX Spark."

### Shot 2 — The box & the stack (0:20–0:40) · *criterion 4*
- **Visual:** the DGX Spark unit; cut to `docs/tech-stack.md` or the architecture diagram.
- **Narration:** name the NVIDIA SDKs (NemoClaw/OpenShell, Nemotron, ComfyUI/FLUX
  Blackwell, NeMo/NIM) and Stepfun `step-3.7-flash` VLM. Emphasize local-compute.

### Shot 3 — Start a run: brief + reference (0:40–1:00) · *criterion 3*
- **Visual:** Brand Kit Gallery → "New Kit". Type the brief, drop the reference image,
  select assets (logo, social_square), click **Start**. Health badges for Ollama +
  ComfyUI are green.
- **Narration:** "One brief, one image. The rest is automated."

### Shot 4 — Brand Analyst extracts the DNA (1:00–1:20) · *criterion 2*
- **Visual:** live run view — the DNA card fills in: palette swatches (hex codes), mood
  words, typography. Event log shows "brand_analyst" + the Stepfun VLM call.
- **Narration:** "Stepfun's multimodal VLM reads the image and the brief, extracts a
  structured brand DNA — palette in hex, mood, typography, dos and don'ts."

### Shot 5 — Art Director plans the manifest (1:20–1:40) · *criterion 2*
- **Visual:** asset lanes appear (planned state) with the Director's per-asset FLUX
  prompts; event log shows "art_director" + "backend: ollama".
- **Narration:** "Local NVIDIA Nemotron, acting as the art director, decomposes the DNA
  into an asset manifest — each asset gets a prompt, composition, and size."

### Shot 6 — Generator + the VRAM-swap log (1:40–2:10) · *criterion 2 (optimization)*
- **Visual:** an asset flips to "rendering"; the event log shows the Model Orchestrator
  events: "ollama_unload" → "comfyui_run" → "ollama_reload". VRAM-free number ticks.
- **Narration:** "Here's the optimization story. The GB10's 120 GiB unified memory is
  shared. A model-orchestrator agent swaps Ollama out before FLUX renders, then reloads
  Nemotron after — no OOM, no idle memory."

### Shot 7 — The critic loop (2:10–2:40) · *criterion 2*
- **Visual:** the Critic scores an asset (e.g. 62, failed) with hex-level feedback
  ("Add missing #C65D3B Ember accent..."). The Director rewrites the prompt; the asset
  re-renders; score improves. The loop is *visible* in the event log.
- **Narration:** "The Stepfun VLM critiques each asset against the DNA — palette match,
  mood, legibility. On a fail, the director rewrites *only that asset's* prompt and
  re-renders. Bounded, early-exit."

### Shot 8 — Final brand kit board (2:40–3:00) · *criterion 3 / 5*
- **Visual:** the Kit Board — all approved assets tiled, palette strip, brand-guide
  preview, optimization stats (vram_swaps, VLM calls, routing). Click **Download kit.zip**.
- **Narration:** "The assembler packages the kit and writes a brand guide. One
  download."

### Shot 9 — Chat-driven (OpenClaw) + sandbox (3:00–3:20) · *criterion 4*
- **Visual:** OpenClaw Web UI `:9000` — type "design a brand kit for ..."; the
  StyleForge skill runs **inside the NemoClaw sandbox**, assets render inline via
  `MEDIA:`. Briefly show the egress policy (deny-by-default, allowlisted to
  `host.openshell.internal:8000`).
- **Narration:** "Same pipeline, chat-driven, and sandboxed — the agent has no secrets
  and deny-by-default network egress."

### Shot 10 — Completeness & quality bar (3:20–3:40) · *criterion 3*
- **Visual:** terminal `make acceptance` → 6/6 PASS; `make coverage` → 87%. Quick cut
  to `tests/golden/golden-001_kit_manifest.json`.
- **Narration:** "84 tests, 87% coverage, a captured golden run, and CI. Not a prototype
  — it's tested."

### Shot 11 — Closing (3:40–3:50) · *criterion 1*
- **Visual:** the final kit board again + tagline.
- **Narration:** "StyleForge — a multi-agent, locally-deployed brand identity studio.
  One brief, one image, a complete on-brand kit."

---

## Notes for the filmer

- The critic loop (Shot 7) is the most compelling visual — make sure a real fail→fix→pass
  is captured (the golden run shows FLUX garbling wordmark text and the critic catching
  it; this is honest and demonstrates the quality gate, not a weakness).
- If `nemotron-3-super:120b` is available for the demo, use it for the Art Director
  (deeper planning); otherwise `nemotron-3-nano:30b` (dev) is fine and faster.
- If Telegram is regionally blocked on the demo network, omit it or show the
  "configured" state without claiming it is live. (See CP-012 notes.)
- Keep on-screen text legible — the palette hex codes and the VRAM-swap log are the
  "evidence" the judges will look for.
