# CP-020: Multi-Reference Image + @N Brief Syntax

**Status:** ✅ done

## Objective

Allow users to upload multiple reference images (1–5) per run and reference them
by index (`@1`, `@2`, …) in their brand brief, so each pipeline stage knows which
image to consult for which purpose.

## Changes

### New module: `src/common/brief_parser.py`
- `parse_image_roles(brief, num_images) -> dict[int, str]` — extracts the sentence
  context around each `@N` token as a "role" description.
- `validate_brief_tokens(brief, num_images)` — raises `BriefTokenError` if any `@N`
  is out of range (`@0` or `@N > num_images`).

### Schema: `src/common/schemas.py`
- `RunInput.reference_image: str` → `reference_images: list[str]` (min 1).
- Added `image_roles: dict[int, str]` to `RunInput`.
- Added `reference_index: int | None` to `AssetSpec` (1-based image index).
- Removed dead `RunOptions.pulid_reference`.
- Added `model_validator` to enforce at least one reference image.

### API: `src/orchestrator/api.py`
- `image: UploadFile` → `image: list[UploadFile]` (1–5 files).
- Saves each as `reference_<N>.<ext>` (preserves original extension).
- Validates `@N` tokens against upload count → 400 on out-of-range.
- Enforces `max_reference_images` (default 5) → 400 on too many.

### Helper: `skills/styleforge/styleforge_helper.py`
- `latest_inbound_image()` → `latest_inbound_images(max_n=5)` — collects up to
  N newest inbound images sorted by mtime (oldest→newest for stable @N ordering).
- `post_run()` sends multiple `image` file parts.
- `_consume_inbound_images()` archives all used images.
- `STYLEFORGE_IMAGE` env supports comma-separated paths.

### Brand Analyst: `src/agents/brand_analyst.py`
- `analyze_brand(brief, images: str | Path | Sequence[str | Path], ...)`.
- VLM message includes one `image_url` block per image, labeled `Image @N:`.
- Cache key = composite `sha1(brief + concat(all_image_bytes))`.
- Prompt updated to instruct synthesis of all images into one brand DNA.

### Art Director: `src/agents/art_director.py`
- `plan_assets(..., image_roles, num_images)` — passes role descriptions to the
  planning prompt so the LLM can set `reference_index` per asset.
- `_build_asset` passes `reference_index` through.

### Runner: `src/orchestrator/runner.py`
- Calls `validate_brief_tokens` + `parse_image_roles` early.
- Passes `reference_images` list to `analyze_brand`.
- Passes `image_roles` + `num_images` to `plan_assets`.
- Post-plan hook `_resolve_reference_indices`: for each `AssetSpec` with
  `reference_index = N`, sets `pulid_reference = reference_images[N-1]`.
  Defaults `uses_pulid=true` assets without an index to image 1.

### Frontend
- `NewKitForm.tsx`: multi-file drop zone with @1 @2 labels, remove buttons.
- `api.ts`: `StartRunInput.images: File[]`, appends multiple `image` parts.

### CLI: `tools/run_pipeline.py`
- `--ref` accepts `nargs="+"` (one or more paths).

## Backward compatibility
- Single image upload works (wrapped as 1-element list).
- `reference_images` with 1 item = old behavior.
- Old runs with `reference.png` (no index) are not affected (iterate mode reuses
  brand_dna.json, not the input files).

## Acceptance tests
- [x] Upload 2 images + brief with @1 @2 → Brand Analyst sees both labeled
- [x] Art Director receives image_roles in planning prompt
- [x] Post-plan hook resolves reference_index → pulid_reference
- [x] Single image upload (no @N) → works as before
- [x] @N out of range → 400 error before pipeline starts
- [x] Too many images (> max) → 400 error
- [x] Frontend shows multiple image thumbnails with @N labels
- [x] Helper collects N newest inbound images, archives all after run
- [x] All 103 tests pass, ruff clean, mypy clean, frontend builds
