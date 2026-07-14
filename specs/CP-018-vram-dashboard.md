# CP-018 — Real-time VRAM orchestration dashboard (DGX Spark showcase)

## Objective
Add a live VRAM dashboard to the gallery UI that visualizes the GB10's 120 GB
unified-memory orchestration in real time: a VRAM gauge, a model-swap timeline
(Ollama ↔ ComfyUI), per-swap latency, and the current active model. This makes
the "only DGX Spark can do this" story visible to judges.

## Motivation
The Model Orchestrator already swaps between Ollama (30 B reasoning) and ComfyUI
(FLUX generation) on the 120 GB unified memory, logging every event. But this is
invisible to the viewer. A live dashboard turns the hidden hardware advantage
into a visible, impressive demo artifact.

## Changes
- `src/orchestrator/api.py`: add `backend` to SSE allowlist (already logged).
- `frontend/src/types.ts`: add `backend` to `SseOrchestratorEvent`.
- `frontend/src/components/VramDashboard.tsx` (new):
  - Animated VRAM gauge (free / used out of 120 GB)
  - Model-swap timeline (horizontal bar chart: Ollama blue, ComfyUI green)
  - Per-swap latency badges
  - Current active model indicator
  - Total swaps + total VLM calls counters
- `frontend/src/components/LiveView.tsx`: embed VramDashboard.
- `frontend/src/index.css`: gauge animation styles.

## Acceptance
- [ ] VRAM gauge updates live during a run (reflects free VRAM changes)
- [ ] Swap timeline shows Ollama ↔ ComfyUI transitions with timestamps
- [ ] Active model indicator shows which model is currently loaded
- [ ] Dashboard visible in LiveView during demo
- [ ] eslint + tsc pass
