# 05 — Frontend Design (Brand Kit Gallery)

> A React + Vite SPA served on `:5173` that gives StyleForge a polished, visual demo
> surface (scoring criterion 3 completeness + 5 demo effect). It talks to the FastAPI
> orchestrator on `:8000`.

## Goals

- Submit a brief + reference image and watch the multi-agent pipeline run live.
- Render the final brand kit as a presentation-quality board.
- Be presentable on the demo video with no terminal in sight.

## Pages / views

1. **Home / New Kit** — brief textarea, brand-name field, drag-drop reference image,
   asset-type checkboxes (logo, hero banner, social, product mockup, business card),
   "Generate Brand Kit" button.
2. **Run Live View** — real-time stream of agent activity:
   - Brand DNA card (palette swatches, mood chips, typography).
   - Asset pipeline lanes (Kanban-ish): each asset shows current state
     (`planned → rendering → critiquing → approved/failed`) with the latest thumbnail.
   - Streaming log panel (agent calls, VRAM swaps from `orchestrator_log`).
3. **Brand Kit Board** — the deliverable view:
   - Hero logo + wordmark tile.
   - Hero banner tile.
   - Social square tile.
   - Product mockup tile.
   - Business card tile (front).
   - Palette strip + typography spec + mood.
   - "Download kit" (zip) + rendered `brand_guide.md` preview.
4. **History** — list of past runs (reads `runs/`); click to reopen a kit.

## API contract (consumed from FastAPI :8000)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/runs` | start a run (multipart: brief, image, options) → `{run_id}` |
| GET | `/api/runs/{id}` | current `kit_manifest.json` + stage |
| GET | `/api/runs/{id}/events` | SSE stream of agent events (for the live view) |
| GET | `/api/runs/{id}/assets/{name}` | serve a PNG |
| GET | `/api/runs/{id}/brand_guide` | serve `brand_guide.md` rendered |
| GET | `/api/runs/{id}/kit.zip` | zip the `brand_kit/` dir |

## Real-time mechanism

- Server-Sent Events (SSE) from `/events`; the backend tails `run.log` +
  `orchestrator_log.json` and pushes structured events.
- Fallback polling every 2s if SSE unsupported.

## Tech choices

- **Vite + React + TypeScript.** Tailwind for styling (fast, demo-clean).
- **State:** lightweight — React Query for server state, `useState`/`useReducer` for UI.
- **No heavy UI lib**; a few focused components keep the bundle small and the demo
  snappy.
- **Image rendering:** plain `<img src="/api/runs/{id}/assets/{name}">` with a loading
  shimmer; failed tiles show a graceful "generation failed" card.

## Out of scope (non-goals)

- Auth / multi-tenant — single-user local app.
- Mobile-first design — desktop presentation is the demo target (responsive is nice-to-have, not required).
- Online deployment — runs only on the DGX Spark over LAN.

## OpenClaw + Telegram parity

The same `kit_manifest.json` powers:
- **OpenClaw Web UI** — the master skill emits `MEDIA:` lines per asset inline.
- **Telegram** — the NemoClaw bridge sends the brand guide text + asset photos.
The Gallery is the "hero" surface; the others prove multi-channel reach.
