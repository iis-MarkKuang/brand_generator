# 04 — ComfyUI Workflow Design (FLUX + PuLID)

> Adapted from the workshop's `face_workflow.json` reference. The workshop
> workflow is the reference for node IDs, model loader names, and the API JSON format.

## Workflow variants

We use **one parameterized workflow** with a conditional PuLID branch:

- **`brand_workflow.json`** — text-to-image brand assets (logo, banner, social, card).
  PuLID branch disabled (`uses_pulid: false`).
- The same workflow with `uses_pulid: true` enables the InsightFace + PuLID identity
  nodes (for mascot/face-consistent assets like a brand character or product mockup
  featuring a person).

## Node graph (API format, node ids are strings)

```
 1  CheckpointLoaderSimple  → flux1-dev-fp8.safetensors
 2  PulidFluxModelLoader    → pulid_flux_v0.9.1.safetensors  (loaded only if uses_pulid)
 3  PulidFluxInsightFaceLoader (CPU provider)
 4  PulidFluxEvaClipLoader
 5  LoadImage               → <pulid_reference>   (only if uses_pulid)
 6  ApplyPulidFlux          (model=1, pulid_flux=2, eva_clip=4, face_analysis=3, image=5, weight=0.9)
 7  CLIPTextEncode (positive) → <flux_prompt>
 8  CLIPTextEncode (negative) → <negative_prompt>
 9  EmptyLatentImage / EmptySD3LatentImage → <width>, <height>
10  KSampler                (model=6 if pulid else 1, positive=7, negative=8, latent=9,
                            seed=<seed>, steps=<steps>, cfg=<cfg>, sampler="euler",
                            scheduler="simple", denoise=1.0)
11  VAEDecode               → IMAGE
12  SaveImage               → <output_filename>
```

> Exact node class names and loader filenames follow the workshop's
> `face_workflow.json` (e.g. `PulidFluxModelLoader`, `pulid_flux_v0.9.1.safetensors`,
> `flux1-dev-fp8.safetensors`). The implementation **reads the workshop workflow as the
> baseline** and only overrides the dynamic fields below.

## Dynamic fields (substituted per asset by the Generator runner)

| Field | Source | Example |
|---|---|---|
| node 7 positive prompt | `AssetSpec.flux_prompt` | "minimalist coffee roaster logo…" |
| node 8 negative prompt | `AssetSpec.negative_prompt` | "photorealistic, 3d, neon…" |
| node 5 image | `AssetSpec.pulid_reference` (if `uses_pulid`) | `runs/<id>/input/reference.jpg` |
| node 9 width/height | `AssetSpec.size` | 1024×1024 |
| node 10 seed | `AssetSpec.seed` | 42125 |
| node 10 steps | `AssetSpec.steps` (default 24; 18 on retry) | 24 |
| node 12 filename | `"<asset_id>__v<attempt>.png"` | `logo__v1.png` |

## Runner protocol (`src/agents/generator.py`)

1. Load `brand_workflow.json` as a dict.
2. If `uses_pulid` is false, prune nodes 2–6 and rewire node 10's `model` input to
   node 1 (the raw CheckpointLoader model). If true, set node 5's image to the
   reference and keep the PuLID chain.
3. Substitute the dynamic fields above.
4. `POST {COMFYUI_HOST}/prompt` with `{"prompt": <graph>}` → get `prompt_id`.
5. Poll `GET {COMFYUI_HOST}/history/{prompt_id}` until the output image appears.
6. Fetch the PNG from `{COMFYUI_HOST}/view?filename=...&subfolder=...`, save into
   `runs/<run_id>/assets/<asset_id>__v<attempt>.png`.
7. Write `render_meta.json` (seed, steps, cfg, latency, vram snapshot).
8. Emit `MEDIA:<abs_path>` for OpenClaw inline rendering.

## Failure handling

- **CUDA context dirty** (workshop-documented signatures: `CUDA error: invalid
  argument`, `illegal memory access`): call `scripts/comfyui-ctl.sh restart`, wait for
  :8200 health, retry the asset **once**.
- **Workflow rejected** (missing node / bad input): return a structured error to the
  Art Director; do not crash the run.
- **Timeout** (no history after `max_wait_s`, default 180): kill the prompt, retry once.

## Asset type → defaults

| type | size | steps | uses_pulid | notes |
|---|---|---|---|---|
| logo | 1024×1024 | 24 | false | high legibility priority |
| hero_banner | 1344×768 | 24 | false | wide composition |
| social_square | 1024×1024 | 24 | false | safe-area aware |
| product_mockup | 1024×1024 | 24 | true (if person) | PuLID for consistency |
| business_card | 1024×576 | 24 | false | print-safe bleed |

> All sizes ≤ 1344 on the longest side to stay within VRAM headroom on GB10 during
  the swap-aware schedule.
