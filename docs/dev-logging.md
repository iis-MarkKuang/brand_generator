# StyleForge 开发者指南：查看 Bot / OpenClaw 日志

本指南介绍如何在 DGX Spark 上查看 StyleForge 各服务的日志，重点是 OpenClaw gateway（Telegram bot）和 FastAPI orchestrator。

---

## 1. 服务架构总览

StyleForge 在 DGX Spark 上运行以下核心服务：

| 服务 | 进程 | 端口 | 管理方式 |
|------|------|------|----------|
| mihomo 代理 | `mihomo` | 7890 (mixed), TUN | systemd user unit `mihomo.service` |
| OpenClaw gateway | `openclaw gateway run` | 9000 | systemd user unit `openclaw.service` |
| FastAPI orchestrator | `uvicorn src.orchestrator.api:app` | 8000 | systemd user unit `fastapi.service` |
| Vite 前端 | `npm run dev` | 5173 | systemd user unit `vite.service` |
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

FastAPI 后端现已配置为 systemd user service（`fastapi.service`），日志输出到 **journald**，崩溃后会自动重启（`Restart=on-failure`，5s 后重启）。

### 3.1 实时日志（推荐）

```bash
# 实时跟踪 FastAPI 日志（Ctrl+C 退出）
journalctl --user -u fastapi -f

# 只看最近 100 行
journalctl --user -u fastapi -n 100 --no-pager

# 只看今天的日志
journalctl --user -u fastapi --since today --no-pager

# 只看错误/警告
journalctl --user -u fastapi -p err --no-pager
```

### 3.2 服务状态 / 重启

```bash
# 查看运行状态、PID、内存、最近崩溃记录
systemctl --user status fastapi

# 查看是否开机自启
systemctl --user is-enabled fastapi

# 重启（修改代码后用）
systemctl --user restart fastapi

# 停止 / 启动
systemctl --user stop fastapi
systemctl --user start fastapi
```

### 3.3 验证崩溃自动恢复

```bash
# 找到 uvicorn 的 PID
systemctl --user show fastapi -p MainPID --value

# 杀掉进程（systemd 会在 5s 内自动拉起新进程）
kill <PID>

# 确认服务已自动恢复
sleep 6 && systemctl --user is-active fastapi
# 期望: active
```

### 3.4 查看运行中的 run 日志

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

## 4. 查看 Vite 前端日志

Vite gallery 现已配置为 systemd user service（`vite.service`），日志输出到 **journald**。

```bash
# 实时跟踪 Vite 日志
journalctl --user -u vite -f

# 最近 50 行
journalctl --user -u vite -n 50 --no-pager

# 状态 / 重启
systemctl --user status vite
systemctl --user restart vite
```

> 注意：Vite 默认监听 `0.0.0.0:5173`，访问 `http://<dgx-ip>:5173`。

---

## 5. 查看 mihomo 代理日志

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

## 6. 查看 Ollama / ComfyUI 日志

这两个服务由 workshop bundle 脚本管理，通常在独立终端中运行：

```bash
# Ollama 日志（如果在后台运行）
journalctl --user -u ollama -f 2>/dev/null || tail -f /tmp/ollama.log

# ComfyUI 日志
tail -f /home/Developer/build_a_claw_workshop-bundle/comfyui-app/ComfyUI/comfyui.log 2>/dev/null
```

---

## 7. 常见问题排查

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

## 8. 一键诊断脚本

```bash
#!/bin/bash
echo "=== mihomo ==="
systemctl --user is-active mihomo && curl -x http://127.0.0.1:7890 -s -o /dev/null -w "proxy: %{http_code}\n" https://api.telegram.org
echo "=== openclaw ==="
systemctl --user is-active openclaw
echo "=== fastapi ==="
systemctl --user is-active fastapi
curl -s http://127.0.0.1:8000/api/health
echo "=== vite ==="
systemctl --user is-active vite
echo "=== ollama ==="
curl -s http://127.0.0.1:11434/api/tags | python3 -c "import sys,json; [print(m['name']) for m in json.load(sys.stdin)['models']]" 2>/dev/null
echo "=== comfyui ==="
curl -s http://127.0.0.1:8200/system_stats | python3 -c "import sys,json; d=json.load(sys.stdin); print('GPU:', d['devices'][0]['name'])" 2>/dev/null
```

---

## 9. systemd user service 配置

StyleForge 的所有常驻服务都通过 systemd user unit 管理，unit 文件位于：

```
~/.config/systemd/user/mihomo.service     # 代理
~/.config/systemd/user/openclaw.service   # Telegram bot / agent gateway
~/.config/systemd/user/fastapi.service    # FastAPI orchestrator (:8000)
~/.config/systemd/user/vite.service       # Vite gallery (:5173)
```

通用关键配置：
- `StandardOutput=journal` / `StandardError=journal` — 日志输出到 journald（可用 journalctl 查看）
- `Restart=on-failure` + `RestartSec=5` — 崩溃后 5s 自动重启
- `EnvironmentFile=/home/Developer/game/.env`（fastapi）— 加载所有 secrets
- `WantedBy=default.target` — 开机自启（配合 linger）

修改任意 unit 文件后需要 reload：

```bash
systemctl --user daemon-reload
systemctl --user restart fastapi vite openclaw mihomo
```

确保用户 linger 已启用（服务在未登录时也能运行）：

```bash
loginctl show-user Developer | grep Linger
# 期望: Linger=yes
```
