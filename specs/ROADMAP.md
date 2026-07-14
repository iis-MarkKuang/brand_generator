# StyleForge — Change-Packet Roadmap

> Spec-driven development plan. Each row is a change packet in `specs/CP-<NNN>-*.md`
> with objective / scope / non-goals / constraints / acceptance tests / relevant context.
> Work one packet per branch; satisfy every acceptance test before marking `done`.
> Status legend: ⬜ ready · 🟡 in-progress · ✅ done · ⏸ blocked.

## Phases & order

| Phase | Purpose | Packets |
|---|---|---|
| 0 Foundation | runnable skeleton + typed contracts | CP-001, CP-002 |
| 1 Core agents | the 5 agents + optimizer | CP-003 → CP-007 |
| 2 Orchestration | wire the loop + OpenClaw skill | CP-008, CP-009 |
| 3 App surface | FastAPI + gallery (the demo) | CP-010, CP-011 |
| 4 Stretch | scoring boosters | CP-012, CP-013, CP-014 |
| 5 Delivery | tests, docs, demo | CP-015, CP-016 |
| 6 Wow factor | VLM depth, DGX Spark showcase, interactivity | CP-017, CP-018, CP-019 |

## Roadmap

| ID | Packet | Phase | Depends on | Status |
|---|---|---|---|---|
| CP-001 | [Foundation: config, schemas, deps, Makefile](CP-001-foundation.md) | 0 | — | ✅ done |
| CP-002 | [Inference client wrappers](CP-002-inference-clients.md) | 0 | CP-001 | ✅ done |
| CP-003 | [Brand Analyst agent (Stepfun VLM)](CP-003-brand-analyst.md) | 1 | CP-001, CP-002 | ✅ done |
| CP-004 | [Art Director agent (local Nemotron)](CP-004-art-director.md) | 1 | CP-001, CP-002, CP-003 | ✅ done |
| CP-005 | [Generator agent (ComfyUI FLUX+PuLID)](CP-005-generator.md) | 1 | CP-001, CP-002 | ✅ done |
| CP-006 | [Critic agent (Stepfun VLM)](CP-006-critic.md) | 1 | CP-001, CP-002, CP-003 | ✅ done |
| CP-007 | [Model Orchestrator (GPU VRAM scheduler)](CP-007-model-orchestrator.md) | 1 | CP-001, CP-002 | ✅ done |
| CP-008 | [Master orchestrator loop + Assembler](CP-008-orchestrator-loop.md) | 2 | CP-003, CP-004, CP-005, CP-006, CP-007 | ✅ done |
| CP-009 | [OpenClaw SKILL.md wiring](CP-009-openclaw-skill.md) | 2 | CP-010 | ✅ done |
| CP-010 | [FastAPI backend service](CP-010-fastapi-backend.md) | 3 | CP-008 | ✅ done |
| CP-011 | [Brand Kit Gallery (React+Vite)](CP-011-frontend-gallery.md) | 3 | CP-010 | ✅ done |
| CP-012 | [NemoClaw sandbox + Telegram always-on](CP-012-nemoclaw-telegram.md) | 4 | CP-009 | ✅ done (sandbox + skill; Telegram LIVE via TUN mode) |
| CP-013 | [NVIDIA NIM cloud model routing](CP-013-nim-routing.md) | 4 | CP-002, CP-004, CP-007 | ✅ done |
| CP-014 | [NeMo LoRA fine-tuning optimization leg](CP-014-nemo-lora.md) | 4 | CP-005 | ✅ done (Generator LoRA + plan; training deferred) |
| CP-015 | [Tests + acceptance harness + golden run](CP-015-tests-golden.md) | 5 | CP-008 | ✅ done |
| CP-016 | [Documentation, deployment guide, demo script](CP-016-documentation.md) | 5 | CP-011, CP-012 | ✅ done |
| CP-017 | [VLM reasoning chain + consistency matrix](CP-017-vlm-reasoning-consistency.md) | 6 | CP-006, CP-008 | ✅ done |
| CP-018 | [Real-time VRAM orchestration dashboard](CP-018-vram-dashboard.md) | 6 | CP-010, CP-011 | ✅ done |
| CP-019 | [Conversational design iteration via Telegram](CP-019-conversational-iteration.md) | 6 | CP-008, CP-012 | ✅ done |

## Dependency graph

```
CP-001 ──► CP-002 ──┬──► CP-003 ──┬──► CP-004 ──┐
                    ├──► CP-005 ──┤             │
                    ├──► CP-006 ──┤             ├──► CP-008 ──► CP-010 ──┬──► CP-009 ──► CP-012 ─┐
                    └──► CP-007 ──┘             │             │         │                        │
                                                │             │         └──► CP-011 ─────────────┤
CP-002 ──► CP-013 (also CP-004, CP-007)         │             │                                  │
CP-005 ──► CP-014                               │             │                                  │
                                CP-008 ──► CP-015             │                                  │
                                CP-011, CP-012 ──► CP-016 ◄───┴──────────────────────────────────┘
```

## Critical path (minimum viable demo)

`CP-001 → CP-002 → CP-003 → CP-004 → CP-005 → CP-006 → CP-007 → CP-008 → CP-010 → CP-011`

> Note: CP-009 (OpenClaw chat surface) now depends on CP-010 because the skill holds no
> secrets and calls the orchestrator API (single secrets boundary,
> `references/design/07-security-and-tokens.md` §A). CP-009 is off the critical path but
> still recommended before the stretch phase.

## Stretch path (score maximizers, time permitting)

`CP-009` (OpenClaw chat surface) → `CP-012` (NemoClaw + Telegram) → `CP-013` (NIM
routing) → `CP-014` (NeMo LoRA). Each adds a distinct rubric point; do in this order
since CP-012 has the best effort/score ratio.

## Cross-cutting: security & token budget (all packets)

Every packet must honor `references/design/07-security-and-tokens.md` and the
`.cursor/rules/security.mdc` rule. Highlights enforced in acceptance tests:
single secrets boundary (only the orchestrator loads `.env`); path-traversal protection
on `/api/runs/{id}/**`; CORS allowlist; upload cap; Telegram `chat_id` allowlist;
global caps `MAX_TOTAL_VLM_CALLS`/`MAX_TOTAL_RENDERS`/`RUN_TIMEOUT_S`; VLM `detail`
tiers; Art Director context is text-only; `flux_prompt` ≤ 600 chars. Run
`tools/check-secrets.sh` before every commit.

## How to use this roadmap

1. Pick the lowest-ID `ready` packet whose dependencies are all `done`.
2. `git checkout -b cp-<NNN>-<slug>` (or use `tools/new-change-packet.sh` for new work).
3. Implement within scope; respect non-goals.
4. Run every acceptance test in the packet; all must pass.
5. Commit with `CP-<NNN>: <message>`; update the packet's status line and this table.
6. Run `tools/check-secrets.sh` before pushing.

## Suggested first commit

Snapshot the design + harness baseline (no code yet) as `CP-000: project design & harness`
so the design docs, AGENTS.md, rules, tools, and specs are versioned before CP-001 starts.
