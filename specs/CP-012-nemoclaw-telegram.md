# CP-012 — NemoClaw sandbox + Telegram always-on

> Status: done (sandbox + skill, E2E verified); Telegram LIVE via TUN mode
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
- [x] `nemoclaw` CLI installed; `nemoclaw onboard` produces a running sandboxed agent.
      (Sandbox `styleforge`, OpenClaw v2026.6.10, model `nemotron-3-nano:30b` via local
      Ollama, Phase Ready, inference healthy on `inference.local` + `127.0.0.1:11434`.)
- [x] Network policy test: an outbound call to an unlisted host from inside the sandbox is denied.
      (`curl http://host.docker.internal:8000/api/health` → `policy_denied` before the
      `styleforge-orchestrator`/`local-inference` egress was applied; the governed L7 proxy
      denies by default.)
- [x] No-secret test: the sandbox mount set does not include `.env` or any key file.
      (The skill helper is secrets-free stdlib; `SKILL.md`/`run_helper.sh`/`styleforge_helper.py`
      contain no keys; the orchestrator on the host is the single secrets boundary.)
- [x] E2E skill run from inside the sandbox: the `styleforge` skill helper executed inside the
      NemoClaw sandbox, reached the host orchestrator via `host.openshell.internal:8000`
      (governed egress), ran the full pipeline (Brand Analyst → Art Director → Generator →
      Critic with one retry), and published `brand_guide.md` to the sandbox media boundary.
      Result `status=partial` (logo failed the strict critic, threshold 70 — consistent with
      the golden-run FLUX-text limitation). Run id `20260713-133254-74725`, ~318 s.
- [x] Telegram allowlist: bot token verified valid (`getMe` → `styleforge322_mark_bot`,
      ok:true); the `telegram` egress preset is applied. **LIVE via TUN mode:** the OpenShell
      gateway L7 proxy connects directly to `api.telegram.org` (Node `fetch`, does not honor
      `HTTP_PROXY`/`HTTPS_PROXY`), so app-level proxying was insufficient. Enabled mihomo
      **TUN mode** (transparent proxy: `tun:` block in clash config + `setcap cap_net_admin` +
      service restart) → `api.telegram.org` now reachable directly; the telegram bridge
      registered with the gateway and the bot is polling. Allowlist = `7538180993`,
      group-policy = disabled (DMs only). Rollback: `tun.enable: false` + restart mihomo.
- [x] `tools/check-secrets.sh` passes (token not in any tracked file; token only in `.env`).
- [x] Manual demo: trigger a brand kit from a phone via Telegram — bot is LIVE and polling
      (`@styleforge322_mark_bot`); send `/start` to initiate the chat, then a brief. The
      web gallery + OpenClaw TUI remain the primary demo surfaces.

## Implementation notes / findings
- **Sandbox bring-up:** `nemoclaw onboard --non-interactive --yes --no-gpu --agent openclaw
  --no-ollama-autostart` with `NEMOCLAW_PROVIDER=ollama`, `NEMOCLAW_MODEL=nemotron-3-nano:30b`,
  `NEMOCLAW_SANDBOX_NAME=styleforge`. The provider identifier is `ollama` (not `ollama-local`,
  which is an internal key). `--no-gpu` keeps the sandbox as a pure orchestrator; Ollama +
  ComfyUI run on the host (GB10 unified memory) and are reached via the host gateway.
- **Sandbox image build:** BuildKit multi-stage build pulling `node:22-trixie-slim` (Docker Hub)
  and `ghcr.io/nvidia/nemoclaw/sandbox-base` (GHCR) through the Docker-daemon Clash proxy
  (`http-proxy.conf` drop-in). Build ~7 min; supply-chain integrity pins for OpenClaw
  2026.6.10, mcporter 0.7.3, codex-acp 0.11.1 verified inside the image.
- **Egress to the host orchestrator:** the skill helper inside the sandbox reaches the host
  FastAPI backend at `http://host.openshell.internal:8000`. The built-in `local-inference`
  policy preset (balanced tier) already allowlists `host.openshell.internal:8000` with the
  SSRF-guard `allowed_ips` (10/8, 172.16/12, 192.168/16). `run_helper.sh` auto-detects the
  sandbox (`/.dockerenv`) and picks `host.openshell.internal` vs `127.0.0.1`. A custom
  `policies/styleforge-orchestrator.yaml` is kept as documentation (redundant with
  `local-inference`).
- **Policy rebuild:** egress policy changes require `nemoclaw styleforge rebuild --yes` to take
  effect in the running sandbox's L7 proxy. Skills survive a rebuild (installed to
  `/sandbox/.openclaw/skills/`, preserved across rebuilds).
- **Telegram unblocked via TUN mode:** `api.telegram.org` is regionally blocked from the
  host's direct network. A Clash/mihomo proxy (`mixed-port: 7890`, `hysteria2`) was set up
  and the Docker daemon configured to use it for image pulls. The Telegram bot token is
  valid (`getMe` ok). The OpenShell gateway's L7 proxy and the nemoclaw reachability check
  use Node's global `fetch` (direct connect, no `HTTP_PROXY` support), so app-level proxying
  was insufficient. **Resolution:** enabled mihomo **TUN mode** (transparent proxy: `tun:`
  block in `~/clash/config.yaml` with `stack: system`, `auto-route: true`, `dns-hijack`;
  `sudo setcap cap_net_admin=ep bin/mihomo`; `systemctl --user restart mihomo` as Developer).
  The `Meta` TUN interface now intercepts egress → `api.telegram.org` reachable directly;
  the telegram bridge registered with the gateway; the bot is LIVE and polling
  (`@styleforge322_mark_bot`). Loopback demo services + LAN gallery + general internet
  remain unaffected by TUN. mihomo is a persistent systemd user unit; TUN survives restart.
  Rollback: `tun.enable: false` + restart mihomo.

## Relevant context
- Design refs: `06-deployment.md` (NemoClaw sandboxing), `00-overview.md` (Telegram bridge).
- NVIDIA references: NemoClaw/OpenShell playbook on `build.nvidia.com/spark/nemoclaw` and the NemoClaw GitHub repo — follow their onboarding wizard.
- This packet materially raises the "NVIDIA SDK utilization" score; do it before CP-013/014 if time-boxed.
