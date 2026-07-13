# CP-009 — OpenClaw SKILL.md wiring

> Status: done
> Depends on: CP-010
> Phase: 2 Orchestration

## Objective
Package the pipeline as an OpenClaw skill so the StyleForge agent is drivable from the
OpenClaw Web UI (`:9000` — configurable via `OPENCLAW_PORT`; workshop notebook uses 3030) chat with inline `MEDIA:` image rendering — proving the
"agent platform" integration for rubric 4. The skill holds **no secrets**: it calls the
FastAPI orchestrator over `localhost:8000` (single secrets boundary, see
`07-security-and-tokens.md` §A).

## Scope
- `skills/styleforge/SKILL.md` — YAML front-matter (`name`, `description` with trigger
  phrases in EN/CN: "generate a brand kit / 品牌视觉识别 / brand identity"), `metadata.openclaw.requires`.
  Body: invoke `run_helper.sh`; explain the `MEDIA:` output protocol per asset.
- `skills/styleforge/run_helper.sh` — bash entrypoint that:
  - does NOT load `.env` (no secrets in the skill); calls `POST http://127.0.0.1:8000/api/runs`
    with the user's brief + inbound reference image (OpenClaw inbound dir), polls
    `GET /api/runs/{id}`, and prints `MEDIA:<abs_path>` lines for each approved asset +
    the brand guide (the orchestrator serves assets at `/api/runs/{id}/assets/{name}`,
    and the helper downloads them to a local temp dir for `MEDIA:` paths if OpenClaw
    requires local file paths).
- `src/orchestrator/cli.py` — thin CLI around `run_pipeline` (loads `.env`) retained for
  local tests/golden runs only; NOT used by the sandboxed skill.
- Respect `$OPENCLAW_HOME` (workshop convention) for skill placement; never hardcode paths.

## Non-goals
- No FastAPI (CP-010) or gallery (CP-011) — this is the chat surface only.
- No NemoClaw sandbox packaging (CP-012) — just the skill; sandbox wraps it later.
- No Telegram (CP-012).

## Constraints
- `description` must be specific enough for the LLM to trigger only on brand-kit intents.
- Skill must not run longer than OpenClaw's call budget without streaming progress;
  emit a one-line "generating…" then `MEDIA:` lines as each asset completes.
- **No secrets in the skill files** — the helper talks to the orchestrator only; it must
  not read `.env` (so it is safe inside the NemoClaw sandbox, CP-012).
- Follow the workshop SKILL.md conventions exactly (notebook §4.2): `MEDIA:` prefix,
  no intermediate file paths in chat, single ~minute-class operations.

## Acceptance tests
- [x] `SKILL.md` front-matter parses; `description` contains the trigger phrases.
- [x] `run_helper.sh` is executable and, with a sample brief + image, produces ≥ one `MEDIA:<abs_path>` line whose file exists. (Live: 2/2 assets approved — `logo.png` + `social_square.png`, 1024×1024 PNGs published into the OpenClaw workspace boundary; 3 min end-to-end.)
- [ ] OpenClaw chat (manual): "帮我生成一个咖啡品牌视觉识别" + attached image triggers the skill and renders asset images inline. (Gateway live at `http://<spark-ip>:9000`; skill symlinked into `$OPENCLAW_HOME/.openclaw/skills/styleforge`. Browser click-through is the user's manual step.)
- [x] `tools/check-secrets.sh` passes on the skill files.
- [x] `make lint && make typecheck` pass.

## Relevant context
- Design refs: `00-overview.md` (component: OpenClaw Gateway), `06-deployment.md` (skill placement under `OPENCLAW_HOME`).
- Workshop reference: notebook §4.2 (SKILL.md format + `MEDIA:` protocol) and §5 (end-to-end chat verification).
- This packet is what makes StyleForge an "AI Agent" in the OpenClaw sense — directly addresses the hackathon's golden requirement #1.
