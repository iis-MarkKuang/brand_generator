# CP-002 — Inference client wrappers

> Status: done
> Depends on: CP-001
> Phase: 0 Foundation

## Objective
Provide one typed async client per inference backend so agents never touch raw HTTP.
Each client is mockable for tests and emits structured logs.

## Scope
- `src/common/stepfun.py` — async `StepfunClient` (OpenAI-compatible, `httpx`).
  Methods: `chat_vlm(messages, reasoning_effort, image_detail="high")` returning parsed
  JSON; helpers `image_to_data_url(path)` and `resize_for_vlm(path, max_side=1024)`
  (pre-resize before encoding to bound tokens — T3). Reads `STEPFUN_*` settings.
- `src/common/ollama.py` — async `OllamaClient`: `chat(model, messages, think=False)`,
  `stop(model)`, `ps()` (loaded models), `vram_probe()` via `nvidia-smi` parsing.
  Reads `OLLAMA_*` settings.
- `src/common/comfyui.py` — async `ComfyUIClient`: `submit(workflow) -> prompt_id`,
  `wait(prompt_id, timeout)`, `fetch_image(filename, subfolder) -> bytes`,
  `health()`. Reads `COMFYUI_HOST`.
- `src/common/nvidia_nim.py` — async `NimClient` (OpenAI-compatible) using
  `NVIDIA_API_KEY` + `NVIDIA_NIM_BASE_URL`; `chat(model, messages)`. Used by CP-013.
- Each client: typed exceptions, retries with backoff for 5xx/timeouts, structured logs
  with model + latency + token/step counts.

## Non-goals
- No agent orchestration (CP-003..008).
- No model routing logic (CP-013) — just expose the NIM client.
- No ComfyUI workflow construction (CP-005) — just the transport.

## Constraints
- All I/O async; no blocking calls.
- Never log request bodies that contain image bytes; log size + hash instead.
- Stepfun JSON-only responses: prompt the model to return strict JSON; client attempts
  `json.loads` and falls back to a repair retry once.

## Acceptance tests
- [ ] `pytest tests/test_stepfun_client.py` — mocked httpx returns JSON → `chat_vlm` parses it.
- [ ] `pytest tests/test_ollama_client.py` — mocked `chat` returns content with `think=False`.
- [ ] `pytest tests/test_comfyui_client.py` — mocked submit/wait/fetch returns PNG bytes.
- [ ] Live smoke (manual, on Spark): `python -c "import asyncio; from src.common.stepfun import StepfunClient; ..."` sends a 1-token VLM request and prints a parsed result.
- [ ] `resize_for_vlm` downsizes a 4096px image to ≤1024px before encoding (assert output dimensions).
- [ ] `make lint && make typecheck` pass.

## Relevant context
- Design refs: `01-agents.md` (per-agent model + effort), `03-model-optimization.md` (O3 effort routing, O6 NIM).
- Workshop quirk: Ollama reasoning models put answer in `message.thinking` unless `think:false` (see notebook §1.3).
- Stepfun base URL: `https://api.stepfun.com/v1`; image input via `image_url` with base64 data URL or URL.
