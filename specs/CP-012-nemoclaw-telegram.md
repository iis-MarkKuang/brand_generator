# CP-012 — NemoClaw sandbox + Telegram always-on

> Status: ready
> Depends on: CP-009
> Phase: 4 Stretch (scoring boosters)

## Objective
Run the StyleForge OpenClaw agent inside a **NemoClaw OpenShell sandbox** (governed,
deny-by-default network, routed inference) and expose it as an always-on **Telegram**
bot — so the brand assistant is reachable from a phone. Directly strengthens rubric 4
(NVIDIA SDK utilization: NemoClaw/OpenShell) and rubric 5 (demo).

## Scope
- NemoClaw onboarding: `nemoclaw onboard` wizard creating a sandboxed OpenClaw agent that
  mounts the `styleforge` skill; blueprint with routed inference to local Ollama.
- Network policy (declarative): allow `127.0.0.1` (Ollama, ComfyUI, OpenClaw),
  `api.stepfun.com`, `integrate.api.nvidia.com` (only if CP-013 enabled); deny rest.
- Filesystem policy: sandbox may write only under its workspace + `runs/`.
- Telegram bridge via NemoClaw's Telegram channel: user sends brief + photo → agent runs
  the skill → brand guide text + asset photos sent back to the chat.
- `docs/deployment.md` section: how to install NemoClaw, run the wizard, wire Telegram.

## Non-goals
- No new agent logic — reuses CP-009 skill.
- No mobile app (Telegram is the mobile surface).
- No multi-user Telegram (single chat/bot).

## Constraints
- `TELEGRAM_BOT_TOKEN` from `.env`; never committed. **The sandbox holds no secrets** —
  the sandboxed agent calls the orchestrator over `localhost:8000`; the token lives only
  in the Telegram bridge process outside the sandbox (single secrets boundary).
- Bot must drop messages from chats not in `TELEGRAM_ALLOWED_CHAT_IDS` **before** any GPU
  work (S4).
- Sandbox must not have broad filesystem or network access — verify the policy denies a
  test outbound call to an unlisted host (S8); verify no secret files are mounted.
- Keep the agent always-on but idle-friendly (no GPU load when not serving a run).

## Acceptance tests
- [ ] `nemoclaw` CLI installed; `nemoclaw onboard` produces a running sandboxed agent.
- [ ] Network policy test: an outbound call to an unlisted host from inside the sandbox is denied.
- [ ] No-secret test: the sandbox mount set does not include `.env` or any key file.
- [ ] Telegram allowlist: a message from an unlisted chat is dropped before any run starts; an allowed chat returns the brand guide + ≥ 1 asset photo.
- [ ] `tools/check-secrets.sh` passes (token not in any tracked file).
- [ ] Manual demo: trigger a brand kit from a phone via Telegram.

## Relevant context
- Design refs: `06-deployment.md` (NemoClaw sandboxing), `00-overview.md` (Telegram bridge).
- NVIDIA references: NemoClaw/OpenShell playbook on `build.nvidia.com/spark/nemoclaw` and the NemoClaw GitHub repo — follow their onboarding wizard.
- This packet materially raises the "NVIDIA SDK utilization" score; do it before CP-013/014 if time-boxed.
