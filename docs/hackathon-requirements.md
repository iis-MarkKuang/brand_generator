# DGX Spark Hackathon — Requirements & Judging Criteria

> Hosted by **NVIDIA** and **Stepfun (阶跃星辰)**. AI-Agent-themed. VLM likely central.

## Submission Requirements (作品提交要求)

1. **Open Source Submission (项目开源提交)** — Full project uploaded to GitHub/Gitee.
   Document progress on CSDN/Zhihu. Submit as a URL link.
2. **Project Documentation (项目说明文档)** — At least **600 words**. Must describe:
   project characteristics, core highlights, detailed technical implementation plan,
   architectural design, and optimization plans.
3. **Deployment Instructions (部署说明)** — Must clearly explain how the AI agent is
   deployed using **local computing power** and how the large models are **optimized**.
4. **Tech Stack Description (技术栈说明)** — Must list the **NVIDIA SDKs** used, plus the
   specific large models from **NVIDIA** and **Stepfun (阶跃星辰)** involved.
5. **Project Demo Video (作品演示视频)** — Video demonstrating functions and core highlights.
6. **Team Information (团队资料)** — Group photo of the team.

## Judging Criteria (评审标准)

| # | Criterion | Weight | Focus | Goal |
|---|-----------|--------|-------|------|
| 1 | Practicality, Industry Landing Value & Technical Innovation | **25%** | Technical implementation, innovative architecture, solutions | Demonstrate DGX Spark advantages, break through traditional thinking, solve a specific technical pain point |
| 2 | Depth of Agent Integration & Model Optimization | **25%** | Multi-agent collaboration, depth of model fine-tuning/optimization | Differentiated technical solutions |
| 3 | Project Completeness | **20%** | Complete functionality, stable operation | Full front+back-end, standardized docs, clear logic, smooth demo |
| 4 | Platform Compatibility | **15%** | Full use of DGX Spark full-stack capabilities | Rational use of NVIDIA open-source models/SDKs + Stepfun "Xingchen" models |
| 5 | Demo Effect | **10%** | Presentation quality | Smooth demo video, clear presentation, intuitive value display |
| 6 | Event Essay | **5%** | Process documentation | Record of results and the "Ten-Day Talk" development journey |

## Golden Requirements (must-haves)

1. **AI Agent focus** — the project must involve an AI Agent.
2. **Mandatory tech stack** — NVIDIA SDKs **and** Stepfun (阶跃星辰) large models.
3. **Local compute & optimization** — emphasize local-hardware deployment and show evidence of model optimization.
4. **Open source & documentation** — open-sourced; docs ≥ 600 words and technically deep.

### Score-maximization strategy
- **50% of the score** sits in (1) Innovation + (2) Agent/Optimization depth →
  prioritize a **multi-agent** system with a real **model-optimization** story over a simple wrapper.
- Use **Stepfun `step-3.7-flash`** (native multimodal VLM, 198B/11B MoE, image+video understanding, tool calling) for vision, and **NVIDIA Nemotron** (local via Ollama) for reasoning.
- Solve a real-world pain point with technical novelty.
- Polish end-to-end demo + detailed process documentation.

## Available platform building blocks (from workshop reference)

- **Hardware:** DGX Spark, GB10 Grace-Blackwell **iGPU** (ARM64, Ubuntu 24.04) with
  **~120 GiB unified memory** shared between CPU and GPU (`nvidia-smi` reports memory as
  `[N/A]`; it is unified, not discrete VRAM), ~1.5 TB disk.
- **Local LLMs (Ollama):** `qwen3.6:35b` (bundled), `nemotron-3-nano:30b` (dev, pulled
  from registry), `nemotron-3-super:120b` (demo, ≈86 GB on disk).
- **Image generation:** ComfyUI + FLUX.1-dev (fp8) + PuLID + InsightFace
  (face-preserving generation, Blackwell FP8 Tensor Core `--fast` mode).
- **Agent platform:** OpenClaw (gateway :9000 — configurable via `OPENCLAW_PORT`; workshop notebook uses 3030, skills = YAML front-matter + markdown body + bash/python helper, `MEDIA:` protocol for inline images in Web UI).
- **NVIDIA SDKs:** NemoClaw (OpenShell sandboxing + governance + routed inference),
  NeMo (specialization/fine-tuning), NIM containers (local inference), Nemotron models.
- **Stepfun models:** `step-3.7-flash` (flagship multimodal reasoning VLM),
  `step-1o-turbo-vision`, `step-1v`, `step-2-16k/mini`. OpenAI-compatible API
  (`https://api.stepfun.com/v1` or `https://api.stepfun.ai/v1`).
- **Key constraint:** GPU memory is **shared** between Ollama and ComfyUI — they swap
  (`ollama models unloaded (free GPU memory for ComfyUI)`). This contention is itself an
  optimization opportunity an agent can manage.
