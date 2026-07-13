# CP-011 — Brand Kit Gallery (React + Vite frontend)

> Status: ready
> Depends on: CP-010
> Phase: 3 App surface

## Objective
Build the polished, visual demo surface: a React + Vite + TS + Tailwind gallery that
submits a brief + reference image, streams the live multi-agent run, and renders the
final brand kit as a presentation-quality board. This is the hero of the demo video
(rubric 5) and a big chunk of "completeness" (rubric 3).

## Scope
- `frontend/` Vite project: React + TS + Tailwind + TanStack Query.
- Pages per `05-frontend.md`: Home/New Kit, Run Live View, Brand Kit Board, History.
- New Kit form: brief, brand name, drag-drop image, asset-type checkboxes, Generate.
- Live View: Brand DNA card (palette swatches, mood chips, typography), asset lanes
  (`planned → rendering → critiquing → approved/failed` with latest thumbnail), streaming
  log panel (agent calls + VRAM swaps from SSE).
- Brand Kit Board: logo, hero banner, social square, product mockup, business card tiles;
  palette strip; typography spec; `brand_guide.md` preview; Download kit.zip.
- History: lists `runs/`; click to reopen a kit.
- SSE consumer on `/api/runs/{id}/events` with 2s polling fallback.
- Failed tiles render a graceful "generation failed" card.

## Non-goals
- No auth, no online deployment (local LAN only).
- No mobile-first (desktop demo target).
- No direct calls to Ollama/ComfyUI/Stepfun — only to FastAPI `:8000`.

## Constraints
- No secrets in frontend; only local FastAPI calls.
- No `any` without an explanatory comment.
- `eslint` + `prettier` pass; `tsc --noEmit` passes.
- Bundle stays small (no heavy UI kit).

## Acceptance tests
- [ ] `npm run build` succeeds; `tsc --noEmit` and `eslint` pass.
- [ ] New Kit → starts a run (mocked API) → Live View shows ≥ 3 staged events.
- [ ] Brand Kit Board renders all asset tiles; a failed tile shows the failure card.
- [ ] Download button fetches `/kit.zip` and triggers a browser download.
- [ ] Manual: on the Spark over LAN, `http://<spark-ip>:5173` shows a real end-to-end run live.
- [ ] No secret strings appear in the built bundle (`grep` the dist for known key prefixes → none).

## Relevant context
- Design refs: `05-frontend.md` (pages, API contract, real-time mechanism).
- This is the most demo-visible packet — prioritize visual polish and the live VRAM-swap log panel (it visually proves the optimization story).
- Coordinate the SSE event shape with CP-010.
