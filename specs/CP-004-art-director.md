# CP-004 — Art Director agent (local Nemotron)

> Status: ready
> Depends on: CP-001, CP-002, CP-003
> Phase: 1 Core agents

## Objective
Implement the Art Director: a tool-calling agent (local Nemotron-3-Super via Ollama) that
takes a `BrandDna` and produces a coherent `AssetManifest` (list of `AssetSpec` with
FLUX prompts), and later (CP-008) drives the generate→critique→refine loop.

## Scope
- `src/agents/art_director.py`:
  - `async def plan_assets(brand_dna, asset_types) -> AssetManifest` — one-shot planning call.
  - `async def rewrite_prompt(asset_spec, critic_feedback) -> AssetSpec` — prompt rewrite on critic fail.
  - Tool-calling scaffolding: declare `analyze_brand`, `generate_asset`, `critic_asset`,
    `request_vram` as tool schemas (implementations wired in CP-005/CP-006/CP-007/CP-008).
- Director system prompt (`prompts/director.md`): enforce **cross-asset consistency**
  (shared palette/type/mood), explicit hex tokens in prompts, asset-type-specific
  composition guidance, and `negative_prompt` for every asset.
- `think=False` for Ollama (workshop quirk) so `message.content` is populated.
- Seed management: deterministic seeds per asset id (reproducible runs).

## Non-goals
- No generation execution (CP-005), no critique (CP-006) — only the planning + rewrite functions and tool schemas here.
- No full loop orchestration (CP-008).
- No NIM cloud routing yet (CP-013) — but design `plan_assets` to accept an injectable client.

## Constraints
- The Art Director's tool-calling context is **text-only**: it holds `brand_dna` (text) +
  `asset_manifest` (text) + per-asset `CriticResult` (text). **Never pass image bytes.**
  Append only the failing asset's feedback, not all prior results (T4).
- On a single asset failure, call `rewrite_prompt` for **that asset only** — never
  re-plan the whole manifest inside the loop (T5).
- Every `AssetSpec.flux_prompt` must include at least 2 palette hex tokens and the brand_name where relevant; ≤ 600 chars.
- `size` longest side ≤ 1344 (VRAM headroom).
- `uses_pulid=true` only for mascot/identity assets; default false.
- Manifest must validate against `AssetManifest`.
- Cache `plan_assets` per `(brand_dna_hash, asset_types)` so iterate runs skip re-planning (T9).

## Acceptance tests
- [ ] `pytest tests/test_art_director.py` — mocked Ollama returns JSON manifest → `plan_assets` returns a validating `AssetManifest` with N asset specs matching requested types.
- [ ] `rewrite_prompt` incorporates `critic_feedback` text into the new prompt (assert substring/semantic via mocked model).
- [ ] Reproducible: same `BrandDna` + seed → identical seeds in the manifest.
- [ ] `make lint && make typecheck` pass.
- [ ] Live smoke (manual): real Nemotron call on a sample `BrandDna` yields 5 coherent asset specs.

## Relevant context
- Design refs: `01-agents.md` (Agent 2, delegating topology), `02-data-contracts.md` (`asset_manifest.json`), `03-model-optimization.md` (O5 smart retry).
- The Art Director becomes the loop driver in CP-008; keep its tool interface stable from this packet.
- Risk: Nemotron 120B is slow; keep planning prompt compact and cacheable per `(brand_dna_hash, asset_types)`.
