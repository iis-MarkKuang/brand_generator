# 参赛证文 — StyleForge：在 DGX Spark 上构建多智能体品牌视觉识别工作室

> DGX Spark Hackathon（NVIDIA × Stepfun 阶跃星辰）参赛历程记录
> 评分维度：赛事征文（5%）— 记录成果与"十日谈"开发旅程

---

## 一、缘起：为什么选这个题目

黑客马拉松的主题是 AI Agent。我们拿到的是一台 NVIDIA DGX Spark 边缘计算盒子——GB10 Grace-Blackwell 集成 GPU，120 GiB 统一内存，ARM64 架构。赛事方还提供了 Stepfun 的多模态 VLM `step-3.7-flash`（198B/11B MoE，原生图像理解 + 工具调用）。

面对这个组合，我们问自己：**什么样的项目能同时展示本地大模型推理、VLM 视觉理解、多智能体协作，还能解决真实世界的问题？**

答案是 StyleForge——一个 AI 品牌视觉识别工作室。用户发一张参考图 + 一句话品牌描述，本地多智能体流水线在 DGX Spark 上生成一整套品牌物料：Logo、Banner、社交媒体图、调色板、品牌指南。整个生成过程在本地完成，只有视觉理解阶段调用 Stepfun VLM。

选择这个题目的原因有三：
1. **真实痛点**：小企业和独立创作者请不起设计公司（通常 $2k–$20k），现有"AI Logo 生成器"只出单图、没有跨资产一致性。StyleForge 模拟人类 Art Director 的约束式多资产共创流程。
2. **技术深度**：需要 LLM 推理（Art Director 规划）、VLM 视觉理解（Brand Analyst 提取品牌 DNA + Critic 评审）、图像生成（ComfyUI FLUX+PuLID），天然适配多智能体架构。
3. **硬件展示**：120 GiB 统一内存的 Ollama↔ComfyUI 交换调度本身就是 DGX Spark 的核心卖点。

---

## 二、架构设计：六智能体流水线

我们设计了六个智能体，每个有明确的输入输出契约（Pydantic 模型，JSON 文件传递）：

```
用户（参考图 + 品牌描述）
  │
  ▼
Brand Analyst（Stepfun VLM）──→ brand_dna.json（调色板、情绪、字体、关键词、dos/don'ts）
  │
  ▼
Art Director（Nemotron 本地 LLM）──→ asset_manifest.json（每个资产的 flux_prompt + 负面提示词）
  │  ↑ 反馈循环
  ▼  │
Generator（ComfyUI FLUX+PuLID）──→ 渲染图片
  │
  ▼
Critic（Stepfun VLM 深度推理链）──→ critic_result.json（分数 + 可操作的修改建议）
  │  │ 不通过 → Art Director 重写 prompt → 重新渲染
  │  │ 通过 ↓
  ▼  ▼
Assembler ──→ kit_manifest.json（品牌包 + 一致性矩阵）
  │
  ▼
Model Orchestrator（GPU 统一内存调度）── 全程管理 Ollama↔ComfyUI VRAM 交换
```

**关键设计决策**：
- Art Director 是**委派型**智能体，不是线性脚本——它根据 Critic 反馈决定重写哪些资产的 prompt。
- 每次智能体间交接都是**验证过的 JSON 文件**，不是内存中的变量——确保可调试、可重放。
- Model Orchestrator 独占 `ollama stop`/`ollama load` 权限——其他组件不能直接操作 VRAM。

---

## 三、开发历程：从骨架到花活

### 第一阶段：基础设施（Day 1-2）

从零开始搭建项目骨架。我们采用了**变更包驱动**的开发流程——每个功能拆成一个小包（`specs/CP-NNN-slug.md`），包含目标、范围、非目标、约束、验收测试。总共拆了 20 个变更包。

首先遇到的是**网络问题**：开发环境在中国，PyPI、HuggingFace、GitHub 全部被墙。解决方案：清华镜像 + `hf-mirror.com` + 代理。幸运的是，DGX Spark 的 workshop bundle 预装了 Ollama（含 CUDA 库）、ComfyUI（含 FLUX/PuLID/InsightFace 模型缓存），省去了大量下载时间。

**关键发现**：GB10 是 Grace-Blackwell **集成 GPU**，120 GiB 统一内存（不是独立显存）。`nvidia-smi` 报告 `[N/A]`。这意味着 Ollama 加载的 30B LLM 和 ComfyUI 的 FLUX 共享同一块内存——需要显式卸载/加载交换。这个"约束"反而成了优化故事的核心。

### 第二阶段：核心智能体（Day 2-5）

逐个实现六个智能体：
- **CP-003 Brand Analyst**：调 Stepfun VLM，从参考图提取结构化品牌 DNA（hex 调色板、情绪关键词、字体建议、dos/don'ts）。
- **CP-004 Art Director**：调本地 Nemotron-3-Nano 30B（Ollama），把品牌 DNA 分解成资产清单，每个资产有 FLUX 提示词。
- **CP-005 Generator**：调 ComfyUI API，FLUX+PuLID 渲染。实现了 CUDA-dirty 自动恢复（检测 CUDA error → 重启 ComfyUI → 重试）。
- **CP-006 Critic**：调 Stepfun VLM，对每张渲染图打分（调色板匹配度、情绪、可读性、品牌一致性），给出 hex 级修改建议。
- **CP-007 Model Orchestrator**：管理 Ollama↔ComfyUI VRAM 交换，记录每次 swap 的原因、VRAM 变化、延迟。

### 第三阶段：编排与界面（Day 5-7）

- **CP-008 主循环**：`run_pipeline()` 串联所有智能体，带 fail-fast（一个资产失败则停止剩余生成）。
- **CP-010 FastAPI 后端**：REST API + SSE 实时流，路径遍历防护、CORS 白名单、上传大小限制。
- **CP-011 前端画廊**：React + Vite + TypeScript + Tailwind，实时展示生成进度、VRAM 仪表盘、一致性矩阵。

### 第四阶段：Telegram 机器人（Day 7-9）

这是**最曲折**的部分。目标：用户在 Telegram 发图 + 文字 → bot 自动生成品牌包 → 发回图片。

**遇到的坑**：
1. **代理不稳定**：Telegram API 在中国被墙，用 mihomo 代理。但代理节点（"宝妈云"）间歇性不可达，导致 gateway polling 循环卡死。解决方案：写了 watchdog 脚本，每 5 分钟检测三种卡死模式（无日志 / 全 fetch-timeout / 有 inbound 但无 skill 活动），自动重启。
2. **Agent 上下文溢出**：qwen3.6:35b 在长对话后上下文溢出，推理卡死 10-47 分钟。解决方案：watchdog 检测到 agent stuck 后清理旧会话文件并重启。
3. **上下文串台**：agent 把上一次 run 的结果混入新 brief。解决方案：SKILL.md 添加"上下文隔离规则" + helper 添加 brief 去重 + 连续运行上限。
4. **自循环**：agent 把自己的输出当成新用户消息，重复触发 run。解决方案：inbound 图归档 + debounce + 连续运行计数。
5. **SOUL.md 未更新**：agent 的系统提示还写着"核心能力是 superhero skill"（workshop 示例），导致 agent 不调用 styleforge。解决方案：重写 SOUL.md。
6. **图片不发**：helper 读 `STYLEFORGE_TG_TOKEN`（安全边界），但 agent 直接调 `.py` 时 env 映射没执行。解决方案：helper 增加 `TELEGRAM_BOT_TOKEN` fallback + 显式代理支持。
7. **日志分裂**：OpenClaw 把关键日志（如 "Inbound message"）只写自己的日志文件，不写 journald。watchdog 只查 journald，漏检 agent 卡死。解决方案：watchdog 同时读两个日志源。

### 第五阶段：花活与优化（Day 9-10）

用户反馈："整个流程简单了一点，没有体现出 DGX Spark 以及 VLM 的牛逼之处。"于是加了三个"花活"：

1. **CP-018 VRAM 编排仪表盘**：前端实时展示 120 GB 统一内存的使用情况、模型交换时间线、计数器。让评委直观看到 DGX Spark 的核心优势。
2. **CP-017 VLM 深度推理链 + 一致性矩阵**：Critic 从单次打分升级为三步推理（描述图像 → 提取渲染调色板 → 带上下文打分）。新增跨资产一致性检查（把所有通过的资产图发给 VLM，比较调色板/字体/情绪/构图的一致性）。
3. **CP-019 对话式迭代**：用户在 Telegram 只发文字（不带图）即可微调上一次的结果（如"logo 再极简一点"）。helper 自动检测迭代模式，只重新渲染需要改的资产。
4. **CP-020 多参考图 @N 语法**：用户可一次发多张图，用 `@1`/`@2` 指定每张图的用途（"@1 是 logo 灵感，@2 是产品包装色调"）。

### 第六阶段：质量与交付（Day 10）

- **代码审查**：用 `fastapi-doctor` 静态分析器审查代码，从 87/100 提升到 99/100（修复 33 个错误 + 30 个警告：安全、正确性、API 规范、韧性、架构）。
- **测试覆盖**：从 84 个测试增长到 126 个，覆盖率 83% → 89%。覆盖了 iterate_run、critic 深度推理、HTTP 重试、多图分析、SSE 去重、一致性检查、VRAM 探测等。
- **CI/CD**：GitHub Actions 跑 ruff + mypy + pytest，修复了 CI 模式下无 `.env` 的 Pydantic 验证错误。
- **文档**：项目说明（1074 字）、部署指南、技术栈说明、演示脚本、开发日志（45K 字）。

---

## 四、技术亮点

### 1. GPU 统一内存调度（DGX Spark 核心展示）

GB10 的 120 GiB 统一内存意味着 Ollama 加载的 30B LLM（~35 GB）和 ComfyUI 的 FLUX（~12 GB）共享同一块内存。Model Orchestrator 在每次生成前卸载 LLM、释放内存给 FLUX，生成完成后再加载回来。这个交换过程在前端 VRAM 仪表盘实时可视化——评委可以看到内存从 62 GB → 90 GB 的波动和每次 swap 的原因/延迟。

### 2. VLM 深度推理链（Stepfun 核心展示）

Critic 不是简单的"打分器"，而是一个三步推理链：
1. **描述**：VLM 用自然语言描述渲染图（"这是一个以奶油色为背景的居中 logo 设计，主体是一个带有咖啡渍纹理的米色圆形…"）
2. **提取调色板**：VLM 从渲染图中提取实际使用的 hex 色值
3. **打分**：带上下文（描述 + 调色板 + 品牌 DNA）进行评分

此外，一致性矩阵把所有通过的资产图一次性发给 VLM，让它评估跨资产的品牌一致性（调色板/字体/情绪/构图），生成热力图可视化。

### 3. 本地↔云模型路由

ReasonRouter 实现 local-first 策略：优先用本地 Ollama（Nemotron），失败时自动 failover 到 NVIDIA NIM 云（`nvidia/llama-3.3-nemotron-super-49b-v1.5`）。路由决策记录在 orchestrator 日志中。

### 4. 安全边界

- **单一密钥边界**：只有 FastAPI 编排器加载 `.env`。OpenClaw skill 和 NemoClaw 沙箱通过 `localhost:8000` 调用编排器，不持有任何密钥。
- **路径遍历防护**：所有文件服务路由验证 `run_id` 正则 + 路径在 `runs/<run_id>/` 内。
- **CORS 白名单**：不用 `*`，只允许配置的来源。
- **上传验证**：用 Pillow 解析图片（不只看扩展名），限制上传大小。
- **Telegram chat_id 白名单**：非白名单用户的消息在 GPU 工作前丢弃。

---

## 五、数据与成果

| 指标 | 数值 |
|---|---|
| 变更包（CP） | 20 个，全部 ✅ done |
| 单元测试 | 126 个，全绿 |
| 代码覆盖率 | 89% |
| Lint/类型检查 | ruff + mypy strict，0 错误 |
| 前端 | tsc + eslint + vite build，全绿 |
| Stepfun VLM 调用 | 285+ 次（品牌分析 + 评审 + 一致性） |
| ComfyUI 渲染 | 50+ 张品牌资产 |
| Git 提交 | 60+ 次 |
| 开发日志 | 45K 字 |
| 支持资产类型 | logo, banner, social_square, product_mockup, business_card |
| 多参考图 | 最多 5 张，@N 语法 |

---

## 六、反思与展望

### 做得好的
- **变更包驱动**：每个功能拆成独立的小包，有明确的验收测试，避免了"大爆炸"式提交。
- **设计文档先行**：7 份设计文档在编码前完成，确保架构一致性。
- **安全意识**：从一开始就建立了密钥边界、路径防护、CORS 限制。
- **渐进式增强**：先跑通基础流程，再加花活（VRAM 仪表盘、深度推理、对话迭代）。

### 踩过的坑
- **网络环境**：中国的网络限制导致大量时间花在代理配置和镜像切换上。
- **Agent 稳定性**：qwen3.6:35b 的上下文溢出和推理卡死是最难调试的问题——进程活着但无响应，需要 watchdog 检测。
- **日志分裂**：OpenClaw 同时写两个日志源（journald + 自己的文件），watchdog 只查一个就漏检。
- **FLUX 的文字渲染局限**：FLUX 不能可靠地渲染文字，导致含文字的 logo 评分低。解决方案：在 prompt 中不要求文字渲染，只在 composition 字段描述排版意图。

### 未来方向
- 用 NeMo Toolkit 做 FLUX LoRA 微调（已搭好训练框架，因时间/内存限制未完成训练）。
- 用 NIM 容器替代 Ollama，提高本地推理吞吐量。
- 用 NemoClaw 沙箱做网络隔离的 agent 运行环境（deny-by-default egress）。
- 支持 product_mockup 和 business_card 资产类型（schema 已就绪）。

---

## 七、致谢

感谢 NVIDIA 和 Stepfun 提供的硬件和 API 支持。DGX Spark 的 120 GiB 统一内存让本地 30B LLM + FLUX 共存成为可能，这是整个项目的硬件基础。Stepfun 的 `step-3.7-flash` VLM 的图像理解能力让品牌分析和评审环节远超简单的打分——它的深度推理链是一致性矩阵的技术前提。

也感谢何老师的 workshop notebook，它提供了 Ollama + ComfyUI + OpenClaw 的基础集成参考，我们在其之上构建了完整的多智能体品牌工作室。

---

*StyleForge — 在 DGX Spark 上，让每个品牌都有自己的视觉身份。*
