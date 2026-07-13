# AGENTS.md — Operating manual for AI coding agents in this repo

> Read this before making changes. It defines the workflow, conventions, and where
> things live. Keep it in sync with `references/design/` and `specs/ROADMAP.md`.

## Project

**StyleForge** — a multi-agent AI brand visual-identity studio for the DGX Spark
Hackathon (NVIDIA × Stepfun). See `references/design/00-overview.md` for the architecture
and `docs/hackathon-requirements.md` for the rules/rubric.

## Workflow: change-packet driven (spec-driven development)

We work in **change packets** — small, individually reviewable units of work. Each
packet lives in `specs/CP-<NNN>-<slug>.md` and contains: objective, scope, non-goals,
constraints, acceptance tests, relevant context. The roadmap is `specs/ROADMAP.md`.

**Rules:**
1. **Always implement within a change packet.** Pick the next `ready` packet from
   `ROADMAP.md` (respect dependencies). If no packet fits the work you were asked to
   do, create one with `tools/new-change-packet.sh "<title>"` and add it to the roadmap
   before coding.
2. **One packet → one branch.** Branch name: `cp-<NNN>-<slug>`. Commit in focused,
   reviewable chunks referencing the packet id in the message
   (`CP-003: extract brand DNA via Stepfun VLM`).
3. **Satisfy every acceptance test** in the packet before marking it `done`. Run the
   acceptance section literally.
4. **Update the roadmap** status (`ready` → `in-progress` → `done`) as you go.
5. **Never skip the design docs.** Any change that diverges from
   `references/design/` must first update the affected design doc and note the
   divergence in the packet's "relevant context".

## Secrets — zero tolerance

- **Never commit `.env` or any real key.** It is gitignored. Only `.env.example`
  templates go in git.
- The hackathon code of conduct explicitly prohibits leaking API keys. If you ever
  see a key in a staged file, unstage it immediately and move the value to `.env`.
- **Single secrets boundary:** only the FastAPI orchestrator (`src/orchestrator/api.py`)
  loads `.env`. The OpenClaw skill and the NemoClaw-sandboxed agent call the orchestrator
  over `localhost:8000` and hold no secrets. See `references/design/07-security-and-tokens.md`.
- Never print secrets to logs, error messages, or the demo video.
- Run `tools/check-secrets.sh` before every commit; run `tools/validate-env.sh` before
  running the app. CI (CP-015) runs the secrets check too.

## Security & token budget

See `.cursor/rules/security.mdc` and `references/design/07-security-and-tokens.md`.
Highlights: path-traversal protection on all `/api/runs/{id}/**` routes; CORS restricted
to `CORS_ALLOWED_ORIGINS` (never `*`); upload size capped; Telegram `chat_id` allowlist;
global caps `MAX_TOTAL_VLM_CALLS`/`MAX_TOTAL_RENDERS`/`RUN_TIMEOUT_S`; VLM `detail` tiers;
Art Director context is text-only.

## Repo layout

```
AGENTS.md                        # this file
.cursor/rules/*.mdc              # persistent agent rules (architecture, workflow, style, secrets)
docs/                            # hackathon requirements, dev journal
references/design/               # architecture source of truth (00–06)
references/workshop-Copy1.ipynb  # the DGX Spark workshop reference
specs/                           # change packets + ROADMAP.md
tools/                           # workflow scripts (new-change-packet, validate-env, check-secrets)
src/
  common/      # config, schemas, client wrappers
  agents/      # brand_analyst, art_director, generator, critic, assembler
  optimizer/   # model_orchestrator
  comfyui/     # brand_workflow.json + runner
  orchestrator/# master loop + FastAPI service
skills/styleforge/               # OpenClaw SKILL.md + run_helper.sh
frontend/                        # React + Vite Brand Kit Gallery
tests/                           # unit + acceptance tests
runs/                            # runtime outputs (gitignored)
cache/                           # brand_dna cache (gitignored)
```

## Tech & style conventions

- **Python 3.12**, type hints everywhere, Pydantic v2 for all data contracts.
- **FastAPI** for the backend, **React + Vite + TypeScript + Tailwind** for the gallery.
- Dependency managers: `uv` (Python) and `npm` (frontend). Lockfiles committed.
- Lint/format: `ruff` + `mypy` (Python), `eslint` + `prettier` (frontend). No PR/commit
  should add lint errors.
- Run `tools/check-secrets.sh` before any commit; run `tools/validate-env.sh` before
  running the app.

## Local services (DGX Spark)

Ollama :11434 (Nemotron), ComfyUI :8200 (FLUX), OpenClaw :3030, FastAPI :8000,
Gallery :5173. Start order & health checks via `make up` (created in CP-001).

## Testing

- Unit tests next to the module (`tests/`). Acceptance tests are defined **in each
  change packet** and must be runnable as written (shell commands or pytest).
- A golden end-to-end run is checked in under `tests/golden/` (input + expected
  `kit_manifest.json` shape) so the orchestrator can be regression-tested.

## When in doubt

- Architecture question → `references/design/00-overview.md`.
- Agent behavior → `references/design/01-agents.md`.
- Data shapes → `references/design/02-data-contracts.md`.
- Optimization claims → `references/design/03-model-optimization.md`.
- Hackathon rules → `docs/hackathon-requirements.md`.
- What to build next → `specs/ROADMAP.md`.
