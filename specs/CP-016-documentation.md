# CP-016 — Documentation, deployment guide, demo script

> Status: done
> Depends on: CP-011, CP-012 (and ideally CP-013/014 for full optimization docs)
> Phase: 5 Delivery

## Objective
Produce every hackathon submission deliverable: the ≥ 600-word project doc, deployment
instructions (local compute + model optimization), tech-stack description (NVIDIA SDKs +
Stepfun models), the demo video script, and the open-source readme polish. Maps to
rubric 3 (completeness), 5 (demo), 6 (essay), and the submission requirements.

## Scope
- `docs/PROJECT.md` — ≥ 600 words: characteristics, core highlights, detailed technical
  implementation, architecture, optimization plans (cite `03-model-optimization.md`).
- `docs/deployment.md` — local deployment on DGX Spark + model optimization steps
  (VRAM scheduling, FP8 fast mode, effort routing, caching, NIM routing, NeMo plan).
- `docs/tech-stack.md` — explicit list of NVIDIA SDKs (NemoClaw/OpenShell, Nemotron,
  ComfyUI/FLUX Blackwell, NeMo, NIM) and Stepfun models (`step-3.7-flash`, `step-2-mini`).
- `docs/demo-script.md` — shot-by-shot demo video script (brief → DNA → manifest →
  render + VRAM-swap log → critic loop → final board → Telegram).
- `README.md` polish: quick start, architecture diagram, tech stack, status, links.
- `docs/dev-journal.md` — finalize the "Ten-Day Talk" journey (rubric 6, 5%).
- Verify open-source readiness: `.env` ignored, no secrets, license file, clean commit history.

## Non-goals
- No new code (docs only) — except README/Makefile touch-ups.
- No filming the video (script only; filming is the team's task).

## Constraints
- PROJECT.md must be ≥ 600 words and technically deep (not marketing fluff) — the rubric is explicit.
- Tech-stack doc must name every NVIDIA SDK and Stepfun model actually used.
- Deployment doc must let a judge reproduce the local bring-up from `.env.example`.
- All docs must be secret-free (`tools/check-secrets.sh` passes).

## Acceptance tests
- [x] `docs/PROJECT.md` word count ≥ 600 (`wc -w` check) and covers all 5 required topics.
      (1074 words; covers characteristics, core highlights, detailed technical
      implementation, architectural design, optimization plans.)
- [x] `docs/tech-stack.md` lists ≥ 4 NVIDIA SDKs and ≥ 1 Stepfun model with usage per item.
      (8 NVIDIA components: DGX Spark/GB10, Nemotron, ComfyUI/FLUX+PuLID, NemoClaw/
      OpenShell, NIM cloud, NeMo, NIM containers, NVIDIA CDI; 2 Stepfun models:
      `step-3.7-flash`, `step-2-mini` — each with role.)
- [x] `docs/deployment.md` includes a reproducible bring-up sequence from a clean clone.
      (Prerequisites → clone+deps → start model services → start StyleForge → optional
      NemoClaw/Telegram → run demo → verify, all from `.env.example`.)
- [x] `docs/demo-script.md` covers the full end-to-end flow in shot list form.
      (11 shots: problem → stack → start → DNA → manifest → VRAM-swap → critic loop →
      final kit → chat+sandbox → completeness → closing.)
- [x] `tools/check-secrets.sh` passes across `docs/` and `README.md`.
- [x] A fresh clone + `cp .env.example .env` (filled) + `make deps && make up` reaches a
      healthy state (manual verification — `make acceptance` 6/6 PASS; `make coverage`
      87%; `curl :8000/api/health` ok).

## Implementation notes
- `LICENSE` added (Apache 2.0) for open-source submission readiness.
- `README.md` polished: quick start (full bring-up), architecture diagram, tech stack,
  status/roadmap table (all 16 CPs ✅), docs index, license link.
- `.gitignore` extended to ignore coverage artifacts (`.coverage`, `coverage_html/`).
- `docs/dev-journal.md` finalized as the "Ten-Day Talk" essay (rubric 6, 5%).

## Relevant context
- Submission requirements: `docs/hackathon-requirements.md` (600-word doc, deployment instructions, tech-stack description, demo video, open-source URL).
- This packet is where the rubric's "documentation" and "essay" points are won; do it last but budget time for it — don't leave it to the final hour.
- Cross-link docs to `references/design/` so judges can drill into architecture if they want.
