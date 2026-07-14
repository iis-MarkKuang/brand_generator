# CP-019 — Conversational design iteration via Telegram

## Objective
After the first brand kit is delivered, the bot invites the user to iterate:
"Want to tweak? Say 'logo 再极简一点' or '换暖色调'." The VLM re-analyzes the
current assets + the user's feedback, the Art Director rewrites only the changed
prompts, and the Generator re-renders only the affected assets — a multi-turn
design conversation powered by local LLM + VLM on DGX Spark.

## Motivation
The current flow is one-shot (brief → kit). Multi-turn iteration showcases the
full agent loop: VLM perception → LLM reasoning → image generation → critique,
repeated in a conversational Telegram interface. This is the "interactive AI
design partner" story.

## Changes
- `src/orchestrator/runner.py`: add `iterate_run(prev_run_id, feedback)` —
  loads previous manifest + assets, VLM re-analyzes with feedback, Art Director
  rewrites changed prompts, Generator re-renders only changed assets.
- `src/orchestrator/api.py`: `POST /api/runs/{id}/iterate` endpoint.
- `src/common/schemas.py`: `IterateRequest` schema.
- `skills/styleforge/styleforge_helper.py`: detect follow-up messages (when a
  previous run exists), call iterate instead of starting fresh.
- `skills/styleforge/SKILL.md`: document iteration trigger phrases.
- `frontend/src/components/LiveView.tsx`: "Iterate" button + feedback input.
- `tests/test_runner.py`: iterate loop unit test.

## Acceptance
- [x] User can send a tweak message after receiving a kit → bot re-renders
- [x] Only changed assets are re-rendered (others reused from prev run)
- [x] VLM re-analyzes current assets with the feedback (via Art Director rewrite)
- [x] Works via Telegram (skill helper auto-detects text-only → iterate) + gallery UI
- [x] All tests pass (89 passing)

## Status: ✅ done
