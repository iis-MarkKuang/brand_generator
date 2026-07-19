# 02 — Data Contracts

> Every inter-agent handoff is a validated JSON file. These schemas are the single
> source of truth — implementations use Pydantic models that mirror them exactly.
> File names are conventional; the *contents* must validate against these schemas.

## `input.json` (run input)

```json
{
  "run_id": "20260713-104200-a1b2",
  "brand_name": "Ember & Oat",
  "brief": "Cozy specialty coffee roaster; warm, craft, hand-made; target young urban professionals.",
  "reference_images": ["runs/<run_id>/input/reference_1.jpg"],
  "image_roles": {},
  "options": {
    "assets": ["logo", "hero_banner", "social_square", "product_mockup", "business_card"],
    "max_retries_per_asset": 2
  }
}
```

## `brand_dna.json` (Brand Analyst output)

```json
{
  "brand_name": "Ember & Oat",
  "palette": [
    {"name": "espresso", "hex": "#3B2417", "rank": "primary"},
    {"name": "oatcream", "hex": "#F3E9D8", "rank": "primary"},
    {"name": "ember",   "hex": "#C26B3C", "rank": "accent"},
    {"name": "moss",    "hex": "#5B6B47", "rank": "accent"},
    {"name": "ink",     "hex": "#1E1A17", "rank": "neutral"}
  ],
  "mood": ["warm", "craft", "earthy", "calm", "handmade"],
  "typography_class": "serif",
  "typography_pairs": {"headline": "warm serif", "body": "humanist sans"},
  "visual_keywords": ["coffee", "steam", "brown-paper", "grain", "hand-drawn", "roaster", "kettle", "wood"],
  "dos":   ["use warm neutrals", "keep generous whitespace", "show texture"],
  "donts": ["neon colors", "glassy 3D", "corporate blue"],
  "personality": "Warm, unhurried, craft-first; feels like a small-batch roaster that cares about origin."
}
```

## `asset_manifest.json` (Art Director output)

```json
{
  "run_id": "20260713-104200-a1b2",
  "brand_dna_ref": "brand_dna.json",
  "assets": [
    {
      "id": "logo",
      "type": "logo",
      "size": [1024, 1024],
      "flux_prompt": "minimalist coffee roaster logo, 'Ember & Oat' wordmark, warm serif, espresso and oat-cream palette, hand-drawn bean motif, centered, generous whitespace, flat vector, high contrast, legible",
      "negative_prompt": "photorealistic, 3d, neon, cluttered, gradient mesh, watermark, text errors",
      "composition": "centered, square-safe",
      "uses_pulid": false,
      "seed": 42125
    },
    {
      "id": "product_mockup",
      "type": "product_mockup",
      "size": [1024, 1024],
      "flux_prompt": "kraft coffee bag mockup on brown-paper table, warm studio light, 'Ember & Oat' label, earthy palette",
      "negative_prompt": "...",
      "composition": "product hero, slight angle",
      "uses_pulid": true,
      "pulid_reference": "runs/<run_id>/input/reference_1.jpg",
      "reference_index": 1,
      "seed": 91837
    }
  ]
}
```

> `uses_pulid: true` is reserved for mascot/identity assets where a reference face or
> character must stay consistent across the kit. Most brand assets are `false`.

## `critic_result.json` (Critic output, per attempt)

```json
{
  "run_id": "20260713-104200-a1b2",
  "asset_id": "logo",
  "attempt": 1,
  "png_path": "runs/<run_id>/assets/logo__v1.png",
  "pass": false,
  "score": 64,
  "palette_match": 0.62,
  "mood_match": 0.80,
  "legibility": 0.55,
  "on_brand": 0.70,
  "feedback": "Palette skews cooler than brand DNA (drop the blue-grey shadow); wordmark legibility drops at small scale — thicken strokes."
}
```

## `kit_manifest.json` (Assembler output — the Gallery contract)

```json
{
  "run_id": "20260713-104200-a1b2",
  "brand_name": "Ember & Oat",
  "status": "complete",
  "brand_dna_ref": "brand_dna.json",
  "brand_guide": "brand_kit/brand_guide.md",
  "assets": [
    {"id": "logo",          "type": "logo",           "path": "brand_kit/logo.png",          "status": "approved", "final_score": 88},
    {"id": "hero_banner",   "type": "hero_banner",    "path": "brand_kit/hero_banner.png",   "status": "approved", "final_score": 84},
    {"id": "product_mockup","type": "product_mockup", "path": "brand_kit/product_mockup.png","status": "approved", "final_score": 90},
    {"id": "social_square", "type": "social_square",  "path": "brand_kit/social_square.png", "status": "failed",   "final_score": null,  "error": "max retries exhausted"}
  ],
  "palette": ["#3B2417", "#F3E9D8", "#C26B3C", "#5B6B47", "#1E1A17"],
  "generated_at": "2026-07-13T10:48:21+08:00",
  "total_latency_s": 312,
  "optimization_stats": {
    "vram_swaps": 6,
    "brand_dna_cache_hit": false,
    "critic_effort_low_count": 4,
    "critic_effort_medium_count": 1
  }
}
```

## `orchestrator_log.json` (Model Orchestrator evidence trail)

```json
{
  "run_id": "20260713-104200-a1b2",
  "events": [
    {"t": "2026-07-13T10:42:31", "action": "unload_ollama", "reason": "pre-generate", "vram_before_gb": 86.0, "vram_after_gb": 1.2, "latency_s": 3.1},
    {"t": "2026-07-13T10:43:12", "action": "load_ollama",   "reason": "post-generate-reason", "vram_before_gb": 1.2, "vram_after_gb": 86.0, "latency_s": 8.4}
  ]
}
```

## Schema rules

- All schemas are implemented as Pydantic v2 models in `src/common/schemas.py`.
- Every JSON file is validated on write **and** on read; a validation error is a hard
  agent failure (never silently passed on).
- Field naming: `snake_case`. Timestamps are ISO-8601 with offset. Paths in JSON are
  **relative to the run dir** unless absolute is explicitly needed (e.g. `MEDIA:` lines).
- Forward-compat: add fields with defaults only; never rename without a migration note.
