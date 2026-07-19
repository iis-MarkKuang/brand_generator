---
name: styleforge
description: "Generate a complete brand visual-identity kit (logo, hero banner, social square, palette, brand guide) from a reference image + a one-line brand brief. Use when: user asks 生成品牌视觉识别, 品牌视觉, 品牌识别, 品牌物料, brand kit, brand identity, brand visual identity, generate a logo + brand assets, or sends a reference image asking for a brand look."
metadata: { "openclaw": { "emoji": "🎨", "requires": { "bins": ["python3", "bash", "curl"] } } }
---

# StyleForge — AI Brand Visual-Identity Studio

发一张参考图 + 一句话品牌简介，本地多智能体流水线（Brand Analyst → Art Director → Generator → Critic）在 DGX Spark 上生成一整套品牌视觉识别包：Logo、Hero Banner、Social Square、调色板、品牌指南。

## Run

helper 会自动从 OpenClaw 的 inbound 目录拿用户**最新上传的参考图**（支持多张，最多 5 张），**brief 作为第一个参数传进去**（把用户的品牌描述原样/精炼后传过来）：

```bash
"$OPENCLAW_HOME/.openclaw/skills/styleforge/run_helper.sh" "<品牌简介，例如：一家温暖的手工小批量咖啡烘焙品牌，手绘衬线字体，浓缩咖啡与燕麦奶油配色>"
```

可选第二参数指定要生成的资产（逗号分隔，默认 `logo,social_square,hero_banner`，可选 `logo,hero_banner,social_square,product_mockup,business_card`）：

```bash
"$OPENCLAW_HOME/.openclaw/skills/styleforge/run_helper.sh" "<brief>" "logo,social_square"
```

`$OPENCLAW_HOME` 是 OpenClaw 启动时注入到 shell 的环境变量，bash 会自动展开。**不要**改写成 `~/.openclaw` 或硬编码路径。

## Multi-reference images + @N syntax (CP-020)

用户可以一次发**多张参考图**（最多 5 张），并在 brief 里用 `@1`/`@2`/… 指定每张图的用途：

```
做一个精品咖啡品牌。
@1 是 logo 灵感参考（极简线条风），
@2 是我想要的产品包装色调，
hero banner 请参考 @2 的氛围，logo 请参考 @1 的风格。
```

- `@1` = 第 1 张上传的图，`@2` = 第 2 张，以此类推
- helper 会按上传顺序（文件 mtime）自动收集 inbound 里的多张图
- Brand Analyst 会看到所有图并标注 @N，综合分析出统一的品牌 DNA
- Art Director 会根据 brief 里的 @N 标注，为每个资产设置 `reference_index`
- 不写 @N 的资产默认参考所有图做整体品牌分析

**注意**：只有发了图片才走 new run；纯文字走 iterate（见下）。

## Iterate (CP-019 — conversational design iteration)

用户收到品牌包后，如果只发文字（不带图）想微调，helper 会自动找到最近一次完成的 run 并迭代：

```bash
"$OPENCLAW_HOME/.openclaw/skills/styleforge/run_helper.sh" "logo 再极简一点，去掉多余的装饰线条"
```

helper 检测到没有新参考图时，会调用 `POST /api/runs/{prev_id}/iterate`，把用户的反馈传给 Art Director 重写 prompt，只重新渲染需要改的资产（其他资产从上一轮复用），再跑一轮 Critic + 一致性检查。

## Output

helper 在 stdout 打印：

- 每个**通过**的资产一行 `MEDIA:<absolute_path_to_png>`（Logo / Hero Banner / Social Square …）
- 最后一行 `Brand guide: <path>` 指向生成的品牌指南 markdown

把**每一整行**（包括 `MEDIA:` 前缀和绝对路径）原封不动复制到你的回复里：

```
你的品牌视觉识别包来啦！🎨
MEDIA:<helper 真正打印的 logo 路径>
MEDIA:<helper 真正打印的 hero banner 路径>
MEDIA:<helper 真正打印的 social square 路径>
Brand guide: <helper 打印的品牌指南路径>
```

OpenClaw Web UI 看到 `MEDIA:` 行会自动把 PNG 渲染成内联图片。如果某些资产没通过 Critic（FLUX 对含文字的 logo 仍有局限），helper 只会输出通过的资产 —— 如实告诉用户哪些通过了、哪些在打磨中即可。

## Rules

- 直接执行，不要先说"正在生成"——helper 内部会轮询，约 2–4 分钟（取决于资产数量）。
- 命令失败时只回复"生成失败，请稍后重试"。
- 不要展示 `OK`、stderr、JSON、文件路径等中间输出，只保留 `MEDIA:` 行 + `Brand guide:` 行 + 一句话寒暄。
- 单次约 2–4 分钟，不要重复触发；用户要改资产清单时再调一次。
- helper **不读 .env、不持有任何密钥** —— 它只调本机 `http://127.0.0.1:8000` 的编排 API（单一密钥边界）。

## Context isolation rules (critical)

- **每张新参考图 = 全新品牌任务**。不要把前一次 run 的品牌名、调色板、设计描述或任何上下文混入新 brief。
- brief 只包含**用户当前消息**里的品牌描述，原样或精炼后传入，不要添加"类似于上次"、"在之前基础上"等引用。
- 只有当用户**明确提到**"改一下上次的"、"微调"、"logo 再极简一点"等迭代意图时，才走 iterate 模式（不带图）。
- 如果用户发了新图 + 新描述，一律走 new run，忽略对话历史中的所有先前 run 输出。
- 不要在 brief 里拼接多轮对话内容——helper 只需要一句话品牌简介。
- 用户发多张图时，保留 brief 里的 `@1`/`@2` 原样传入，helper 和后端会自动解析。
