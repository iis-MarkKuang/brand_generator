# StyleForge 开发者指南：查看 Bot / OpenClaw 日志

本指南介绍如何在 DGX Spark 上查看 StyleForge 各服务的日志，重点是 OpenClaw gateway（Telegram bot）和 FastAPI orchestrator。

---

## 1. 服务架构总览

StyleForge 在 DGX Spark 上运行以下核心服务：

| 服务 | 进程 | 端口 | 管理方式 |
|------|------|------|----------|
| mihomo 代理 | `mihomo` | 7890 (mixed), TUN | systemd user unit `mihomo.service` |
| OpenClaw gateway | `openclaw gateway run` | 9000 | systemd user unit `openclaw.service` |
| FastAPI orchestrator | `uvicorn src.orchestrator.api:app` | 8000 | 手动 / tmux |
| Vite 前端 | `npm run dev` | 5173 | 手动 / tmux |
| Ollama | `ollama serve` | 11434 | workshop bundle 脚本 |
| ComfyUI | `python main.py` | 8200 | workshop bundle 脚本 |

---

## 2. 查看 OpenClaw / Telegram Bot 日志

### 2.1 实时日志（推荐）

OpenClaw gateway 现已配置为 systemd user service，日志输出到 **journald**：

```bash
# 实时跟踪 gateway 日志（Ctrl+C 退出）
journalctl --user -u openclaw -f

# 只看最近 100 行
journalctl --user -u openclaw -n 100 --no-pager
```

### 2.2 OpenClaw 自带的日志文件

OpenClaw gateway 还会写自己的日志文件到 `/tmp/openclaw/`：

```bash
# 当天日志
tail -f /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log

# 查找所有历史日志
ls -la /tmp/openclaw/
```

### 2.3 查看服务状态

```bash
# 查看 gateway 运行状态、内存、PID
systemctl --user status openclaw

# 查看是否开机自启
systemctl --user is-enabled openclaw
```

### 2.4 重启 gateway

```bash
# 正常重启
systemctl --user restart openclaw

# 停止 / 启动
systemctl --user stop openclaw
systemctl --user start openclaw
```

---

## 3. 查看 FastAPI Orchestrator 日志

FastAPI 后端通常在 tmux 会话或前台终端中运行。

### 3.1 如果在前台终端运行

直接查看该终端输出即可。日志包含每个 agent 的调用、Critic 评分、Model Orchestrator 的 VRAM 调度事件等。

### 3.2 查看运行中的 run 日志

每次 run 的详细事件都记录在 `runs/<run_id>/orchestrator_log.json`：

```bash
# 查看最新 run 的事件流
ls -t runs/ | head -1  # 找到最新 run_id
cat runs/<run_id>/orchestrator_log.json | python3 -m json.tool | head -50
```

事件类型包括：
- `brand_dna_extracted` — Brand Analyst 完成
- `asset_planned` — Art Director 规划完成
- `render_started` / `render_completed` — Generator 渲染
- `critic_scored` — Critic 评分
- `model_swap` — Model Orchestrator 切换 Ollama ↔ ComfyUI
- `routing` — ReasonRouter 路由决策（local / NIM cloud）
- `consistency_checked` — 跨资产一致性检查
- `kit_assembled` — 品牌包组装完成

---

## 4. 查看 mihomo 代理日志

```bash
# 实时日志
journalctl --user -u mihomo -f

# 状态
systemctl --user status mihomo
```

如果 Telegram bot 无法连接 `api.telegram.org`，首先检查 mihomo 是否正常运行，以及代理节点是否可达：

```bash
# 测试代理连通性
curl -x http://127.0.0.1:7890 -s -o /dev/null -w "%{http_code}\n" https://api.telegram.org
# 期望: 200
```

---

## 5. 查看 Ollama / ComfyUI 日志

这两个服务由 workshop bundle 脚本管理，通常在独立终端中运行：

```bash
# Ollama 日志（如果在后台运行）
journalctl --user -u ollama -f 2>/dev/null || tail -f /tmp/ollama.log

# ComfyUI 日志
tail -f /home/Developer/build_a_claw_workshop-bundle/comfyui-app/ComfyUI/comfyui.log 2>/dev/null
```

---

## 6. 常见问题排查

### Bot 没有响应

1. **检查 gateway 是否在运行**：`systemctl --user status openclaw`
2. **检查代理是否正常**：`curl -x http://127.0.0.1:7890 -s https://api.telegram.org`
3. **查看 gateway 日志**：`journalctl --user -u openclaw -n 50 --no-pager`
   - 如果看到 `Context overflow` → agent session 卡住，重启 gateway
   - 如果看到 `polling cycle` → bot 正在正常轮询
   - 如果看到 `SSL_ERROR_SYSCALL` → 代理节点故障，切换节点

### Bot 回复了但内容不对

1. **检查 skill 是否正确加载**：`ls -la /home/Developer/build_a_claw_workshop-bundle/openclaw-home/.openclaw/skills/styleforge/`
2. **检查 helper 输出**：`journalctl --user -u openclaw -f` 然后发送消息观察 `[styleforge]` 开头的行

### 生成失败

1. **检查 FastAPI 是否在运行**：`curl http://127.0.0.1:8000/api/health`
2. **检查 Ollama 模型**：`ollama list | grep nemotron`
3. **检查 ComfyUI**：`curl http://127.0.0.1:8200/system_stats`
4. **查看 run 日志**：`cat runs/<run_id>/orchestrator_log.json | python3 -m json.tool`

---

## 7. 一键诊断脚本

```bash
#!/bin/bash
echo "=== mihomo ==="
systemctl --user is-active mihomo && curl -x http://127.0.0.1:7890 -s -o /dev/null -w "proxy: %{http_code}\n" https://api.telegram.org
echo "=== openclaw ==="
systemctl --user is-active openclaw
echo "=== fastapi ==="
curl -s http://127.0.0.1:8000/api/health
echo "=== ollama ==="
curl -s http://127.0.0.1:11434/api/tags | python3 -c "import sys,json; [print(m['name']) for m in json.load(sys.stdin)['models']]" 2>/dev/null
echo "=== comfyui ==="
curl -s http://127.0.0.1:8200/system_stats | python3 -c "import sys,json; d=json.load(sys.stdin); print('GPU:', d['devices'][0]['name'])" 2>/dev/null
```

---

## 8. systemd user service 配置

OpenClaw gateway 的 systemd unit 文件位于：

```
~/.config/systemd/user/openclaw.service
```

关键配置：
- `StandardOutput=journal` — 日志输出到 journald（可用 journalctl 查看）
- `Restart=on-failure` — 崩溃后自动重启
- `After=mihomo.service` — 依赖代理服务
- `Environment=TELEGRAM_BOT_TOKEN=...` — Telegram bot token
- `Environment=TELEGRAM_ALLOWED_CHAT_IDS=7538180993` — 允许的 chat ID

修改配置后需要 reload：

```bash
systemctl --user daemon-reload
systemctl --user restart openclaw
```

确保用户 linger 已启用（服务在未登录时也能运行）：

```bash
loginctl show-user Developer | grep Linger
# 期望: Linger=yes
```
