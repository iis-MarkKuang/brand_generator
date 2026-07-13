# CP-016 — Documentation, deployment guide, demo script

> Status: ready
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
- [ ] `docs/PROJECT.md` word count ≥ 600 (`wc -w` check) and covers all 5 required topics.
- [ ] `docs/tech-stack.md` lists ≥ 4 NVIDIA SDKs and ≥ 1 Stepfun model with usage per item.
- [ ] `docs/deployment.md` includes a reproducible bring-up sequence from a clean clone.
- [ ] `docs/demo-script.md` covers the full end-to-end flow in shot list form.
- [ ] `tools/check-secrets.sh` passes across `docs/` and `README.md`.
- [ ] A fresh clone + `cp .env.example .env` (filled) + `make deps && make up` reaches a healthy state (manual verification).

## Relevant context
- Submission requirements: `docs/hackathon-requirements.md` (600-word doc, deployment instructions, tech-stack description, demo video, open-source URL).
- This packet is where the rubric's "documentation" and "essay" points are won; do it last but budget time for it — don't leave it to the final hour.
- Cross-link docs to `references/design/` so judges can drill into architecture if they want.
