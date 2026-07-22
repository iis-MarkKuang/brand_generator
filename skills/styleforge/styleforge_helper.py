#!/usr/bin/env python3
"""StyleForge OpenClaw skill helper (secrets-free, stdlib-only).

Pipeline:
  1. Auto-discover the user's reference image in OpenClaw's inbound boundary.
  2. POST the brief + image to the local FastAPI orchestrator (/api/runs).
  3. Poll GET /api/runs/{id} until the run assembles (or fails).
  4. For each APPROVED asset, download its PNG from /api/runs/{id}/kit/{id}.png
     and republish it into OpenClaw's media boundary, printing `MEDIA:<abs>`.
  5. Fetch the brand guide and print `Brand guide: <path>`.

No secrets: this script never reads .env and only talks to localhost:8000.
Pure standard library so it runs inside the NemoClaw sandbox (CP-012) with
no venv and no third-party packages.

Usage:
  styleforge_helper.py "<brief>" [assets]
  styleforge_helper.py "warm craft coffee roaster" "logo,social_square,banner"

Environment:
  OPENCLAW_HOME     — OpenClaw home (media/workspace boundary)
  STYLEFORGE_API    — orchestrator base URL (default http://127.0.0.1:8000)
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import mimetypes
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

OPENCLAW_HOME = Path(os.environ.get("OPENCLAW_HOME", "")).resolve() or None
API = os.environ.get("STYLEFORGE_API", "http://127.0.0.1:8000").rstrip("/")
# OpenClaw's media boundary: MEDIA: paths must resolve inside this dir.
PUBLISH_ROOT = (
    (OPENCLAW_HOME / ".openclaw" / "workspace" / "outputs" / "styleforge")
    if OPENCLAW_HOME
    else Path("/tmp/styleforge_outputs")
)
INBOUND_DIR = (OPENCLAW_HOME / ".openclaw" / "media" / "inbound") if OPENCLAW_HOME else None
DEFAULT_ASSETS = "logo,social_square,banner"
POLL_INTERVAL_S = 4
POLL_TIMEOUT_S = 480  # 8 min ceiling for a chat turn


def log(msg: str) -> None:
    print(f"[styleforge] {msg}", file=sys.stderr, flush=True)


# Key milestone log — only for decisive events the user should see.
# Regular log() is for debug noise; key_log() is for important progress updates.
def key_log(msg: str) -> None:
    print(f"[styleforge] ★ {msg}", file=sys.stderr, flush=True)


def _http_json(req: urllib.request.Request, body: bytes | None = None) -> object:
    req.data = body
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 — localhost
            raw = resp.read()
            ctype = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {detail}") from exc
    if "application/json" in ctype:
        return json.loads(raw.decode("utf-8"))
    return raw


def latest_inbound_image(max_age_s: int = 600) -> Path | None:
    """Newest image in OpenClaw's inbound boundary (workshop convention).

    Only images modified within the last ``max_age_s`` seconds are considered,
    so stale images from previous turns don't get reused on a fresh skill
    invocation (which would turn a text-only iterate request into a new run).
    """
    if not INBOUND_DIR or not INBOUND_DIR.is_dir():
        return None
    cutoff = time.time() - max_age_s
    candidates = [
        p
        for p in INBOUND_DIR.iterdir()
        if p.is_file()
        and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        and p.stat().st_mtime >= cutoff
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def latest_inbound_images(max_n: int = 5, max_age_s: int = 600) -> list[Path]:
    """Up to ``max_n`` newest inbound images (sorted oldest→newest for stable @N ordering).

    CP-020: collects multiple reference images so users can upload several and
    reference them by ``@1``/``@2``/… in their brief. Only images modified within
    the last ``max_age_s`` seconds are considered (600s = 10min, giving the agent
    enough time to process the message and invoke the helper).
    """
    if not INBOUND_DIR or not INBOUND_DIR.is_dir():
        return []
    cutoff = time.time() - max_age_s
    candidates = [
        p
        for p in INBOUND_DIR.iterdir()
        if p.is_file()
        and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        and p.stat().st_mtime >= cutoff
    ]
    if not candidates:
        return []
    # Sort by mtime ascending (oldest first) so @1 = first uploaded, @N = last.
    candidates.sort(key=lambda p: p.stat().st_mtime)
    return candidates[-max_n:]


def derive_brand_name(brief: str) -> str:
    words = [w for w in brief.replace(",", " ").split() if w]
    if not words:
        return "Untitled"
    name = " ".join(words[:3])
    return name[:40]


def post_run(brief: str, image_paths: list[Path], brand_name: str, assets: str) -> str:
    """multipart/form-data POST to /api/runs → run_id (stdlib only).

    CP-020: sends one or more ``image`` file parts so the backend receives a
    list of reference images. The brief may use ``@1``/``@2``/… tokens.
    """
    boundary = f"----styleforge{uuid4().hex}"
    fields: list[tuple[str, str]] = [
        ("brief", brief),
        ("brand_name", brand_name),
        ("assets", assets),
        ("max_retries", "1"),
    ]
    buf = io.BytesIO()
    for key, val in fields:
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        buf.write(f"{val}\r\n".encode())
    # image file parts (one per reference image)
    for img_path in image_paths:
        mime = mimetypes.guess_type(str(img_path))[0] or "image/png"
        fname = img_path.name
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(f'Content-Disposition: form-data; name="image"; filename="{fname}"\r\n'.encode())
        buf.write(f"Content-Type: {mime}\r\n\r\n".encode())
        buf.write(img_path.read_bytes())
        buf.write(b"\r\n")
    buf.write(f"--{boundary}--\r\n".encode())
    body = buf.getvalue()
    req = urllib.request.Request(
        f"{API}/api/runs",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    data = _http_json(req, body)
    if not isinstance(data, dict) or "run_id" not in data:
        raise RuntimeError(f"unexpected /api/runs response: {data!r}")
    return str(data["run_id"])


def find_latest_assembled_run() -> str | None:
    """GET /api/runs → return the most recent run_id with status 'assembled'."""
    try:
        data = _http_json(urllib.request.Request(f"{API}/api/runs", method="GET"))
        runs = (
            data
            if isinstance(data, list)
            else (data.get("runs", []) if isinstance(data, dict) else [])
        )
        for r in runs:  # already sorted newest-first by the API
            if isinstance(r, dict) and r.get("status") == "assembled":
                rid = str(r.get("run_id", "")).strip()
                return rid or None
        return None
    except Exception as exc:  # noqa: BLE001
        log(f"find_latest_assembled_run failed: {exc}")
        return None


def post_iterate(prev_run_id: str, feedback: str) -> str:
    """POST /api/runs/{prev_id}/iterate (JSON) → new run_id (CP-019)."""
    body = json.dumps({"feedback": feedback, "assets": []}).encode("utf-8")
    req = urllib.request.Request(
        f"{API}/api/runs/{prev_run_id}/iterate",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    data = _http_json(req, body)
    if not isinstance(data, dict) or "run_id" not in data:
        raise RuntimeError(f"unexpected /iterate response: {data!r}")
    return str(data["run_id"])


def poll_until_assembled(run_id: str) -> dict:
    deadline = time.time() + POLL_TIMEOUT_S
    last_stage = ""
    while time.time() < deadline:
        req = urllib.request.Request(f"{API}/api/runs/{run_id}", method="GET")
        data = _http_json(req)
        if not isinstance(data, dict):
            raise RuntimeError(f"unexpected run status response: {data!r}")
        stage = str(data.get("stage", ""))
        if stage != last_stage:
            # Only log key stage transitions (not every poll)
            stage_labels = {
                "analyzing": "🔍 Brand Analyst analyzing reference image…",
                "planning": "🧠 Art Director planning asset manifest…",
                "generating": "🎨 Generator rendering assets…",
                "reasoning": "🔍 Critic reviewing rendered assets…",
                "assembled": "📦 Assembling brand kit…",
            }
            if stage in stage_labels:
                key_log(stage_labels[stage])
            last_stage = stage
        if stage == "assembled":
            man = data.get("manifest")
            if isinstance(man, dict):
                return man
            raise RuntimeError("assembled but no manifest present")
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError(f"run {run_id} did not assemble within {POLL_TIMEOUT_S}s")


def download_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, method="GET")
    raw = _http_json(req)
    if not isinstance(raw, (bytes, bytearray)):
        raise RuntimeError(f"unexpected download response type: {type(raw)!r}")
    return bytes(raw)


def publish(name: str, run_id: str, data: bytes) -> Path:
    out_dir = (PUBLISH_ROOT / run_id).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = (out_dir / name).resolve()
    if not str(dst).startswith(str(PUBLISH_ROOT.resolve())):
        raise RuntimeError(f"refusing to write outside media boundary: {dst}")
    dst.write_bytes(data)
    return dst


def fetch_brand_guide(run_id: str) -> str:
    try:
        return download_bytes(f"{API}/api/runs/{run_id}/brand_guide").decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 — brand guide is best-effort
        log(f"brand guide fetch skipped: {exc}")
        return ""


# ---------------------------------------------------------------------------
# Telegram direct delivery (optional — only if bot token is in env)
# ---------------------------------------------------------------------------
TG_TOKEN = (
    os.environ.get("STYLEFORGE_TG_TOKEN", "").strip()
    or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
)
TG_CHAT = (
    os.environ.get("STYLEFORGE_TG_CHAT", "").strip().split(",")[0].strip()
    or os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").strip().split(",")[0].strip()
)
TG_API = "https://api.telegram.org"


def _tg_post(
    endpoint: str,
    fields: list[tuple[str, str]],
    photo: bytes | None = None,
    photo_fname: str = "asset.png",
) -> dict:
    """POST to Telegram Bot API (stdlib multipart). Returns parsed JSON."""
    boundary = f"----tg{uuid4().hex}"
    buf = io.BytesIO()
    for key, val in fields:
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        buf.write(f"{val}\r\n".encode())
    if photo is not None:
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(
            f'Content-Disposition: form-data; name="photo"; filename="{photo_fname}"\r\n'.encode()
        )
        buf.write(b"Content-Type: image/png\r\n\r\n")
        buf.write(photo)
        buf.write(b"\r\n")
    buf.write(f"--{boundary}--\r\n".encode())
    body = buf.getvalue()
    url = f"{TG_API}/bot{TG_TOKEN}/{endpoint}"
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    # Build opener with explicit proxy support for robustness inside OpenClaw.
    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""
    if proxy_url:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"https": proxy_url, "http": proxy_url})
        )
    else:
        opener = urllib.request.build_opener()
    with opener.open(req, timeout=30) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def send_telegram_text(text: str) -> None:
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        _tg_post("sendMessage", [("chat_id", TG_CHAT), ("text", text[:4096])])
        log(f"telegram text sent ({len(text)} chars)")
    except Exception as exc:  # noqa: BLE001
        log(f"telegram text send failed: {exc}")


def send_telegram_photo(image: bytes, caption: str) -> None:
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        _tg_post(
            "sendPhoto",
            [("chat_id", TG_CHAT), ("caption", caption[:1024])],
            photo=image,
            photo_fname="brand_asset.png",
        )
        log(f"telegram photo sent ({len(image)} bytes, caption {len(caption)} chars)")
    except Exception as exc:  # noqa: BLE001
        log(f"telegram photo send failed: {exc}")


def _strip_markdown(text: str) -> str:
    """Convert markdown to plain readable text for Telegram."""
    import re as _re

    # Headers: ## Title → Title (remove #)
    text = _re.sub(r"^#{1,6}\s*", "", text, flags=_re.MULTILINE)
    # Bold: **text** → text
    text = _re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    # Italic: *text* → text
    text = _re.sub(r"\*(.+?)\*", r"\1", text)
    # Code: `text` → text
    text = _re.sub(r"`(.+?)`", r"\1", text)
    # Table rows: | a | b | → a: b
    text = _re.sub(
        r"^\|(.+)\|$", lambda m: "  " + m.group(1).replace(" | ", " · "), text, flags=_re.MULTILINE
    )
    # Table separator: |---|---| → remove
    text = _re.sub(r"^\|[-:|\s]+\|$", "", text, flags=_re.MULTILINE)
    # Bullet lists: - item → • item
    text = _re.sub(r"^[\s]*[-*]\s+", "  • ", text, flags=_re.MULTILINE)
    # Multiple blank lines → single
    text = _re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _hex_to_emoji(hex_color: str) -> str:
    """Pick a colored circle emoji closest to the hex color."""
    h = hex_color.lstrip("#").upper()
    dark = ("1", "2", "3", "4", "5")
    mid = ("6", "7", "8", "9", "A", "B")
    light = ("C", "D", "E", "F")
    if h and h[0] in dark:
        return "⚫"
    if h and h[0] in light:
        return "⚪"
    if h and h[0] in mid:
        return "🟡"
    return "🔴"


def deliver_to_telegram(approved: list, run_id: str, palette: list, brand_guide: str) -> None:
    """Send each approved asset as a Telegram photo + a nicely formatted summary."""
    if not TG_TOKEN or not TG_CHAT:
        log("telegram delivery skipped (no STYLEFORGE_TG_TOKEN / chat id)")
        return
    labels = {"logo": "Logo", "social_square": "Social Square", "banner": "Banner"}

    # Send each asset photo with a clean caption
    sent = 0
    for a in approved:
        aid = str(a.get("id", "")).strip()
        if not aid:
            continue
        try:
            png = download_bytes(f"{API}/api/runs/{run_id}/kit/{aid}.png")
            label = labels.get(aid, aid)
            score = a.get("score", a.get("final_score", "?"))
            caption = f"🎨 {label} — Critic score: {score}/100 ✅"
            send_telegram_photo(png, caption)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            log(f"could not send {aid} to telegram: {exc}")

    # Build a nicely formatted summary
    lines = []
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("✅ StyleForge 品牌包生成完成")
    lines.append(f"📦 {sent} 项资产已交付")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    # Palette section with colored emoji
    if palette:
        lines.append("🎨 品牌色板:")
        for p in palette[:5]:
            if isinstance(p, dict):
                name = p.get("name", "")
                hex_val = p.get("hex", "")
                rank = p.get("rank", "")
                emoji = _hex_to_emoji(hex_val)
                rank_label = {"primary": "主色", "accent": "强调色", "neutral": "中性色"}.get(
                    rank, ""
                )
                lines.append(f"  {emoji} {name} {hex_val} ({rank_label})")
            else:
                lines.append(f"  ⚪ {p}")
        lines.append("")

    # Asset summary
    lines.append("📋 资产清单:")
    for a in approved:
        aid = str(a.get("id", "")).strip()
        label = labels.get(aid, aid)
        score = a.get("score", a.get("final_score", "?"))
        lines.append(f"  ✅ {label} — {score}/100")
    lines.append("")

    # Brand guide excerpt (stripped of markdown)
    if brand_guide:
        guide_text = _strip_markdown(brand_guide[:1200])
        lines.append("📖 品牌指南 (摘要):")
        lines.append(guide_text)
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🆔 Run ID: {run_id}")
    lines.append("💬 发送纯文字消息可继续微调设计")

    summary = "\n".join(lines)
    send_telegram_text(summary)


def _debounce_lock(cooldown_s: int = 180) -> bool:
    """Prevent rapid-fire re-invocation (agent self-loop protection).

    Returns True if we should PROCEED, False if a recent run is still in
    flight / just finished and we should skip this invocation. Uses a
    mtime-based stamp file under /tmp so it works across processes.
    """
    stamp = Path("/tmp/styleforge_helper_last_run.ts")
    with contextlib.suppress(OSError):
        if stamp.is_file() and (time.time() - stamp.stat().st_mtime) < cooldown_s:
            return False
    with contextlib.suppress(OSError):
        stamp.write_text(str(time.time()))
    return True


def _brief_dedup(brief: str) -> bool:
    """Skip if the brief is identical to the last one (agent self-echo guard).

    Returns True if we should PROCEED, False if the brief matches the
    previous invocation (the agent is echoing its own output).
    """
    brief_hash = hashlib.sha256(brief.encode("utf-8"), usedforsecurity=False).hexdigest()
    stamp = Path("/tmp/styleforge_helper_last_brief.hash")
    with contextlib.suppress(OSError):
        if stamp.is_file() and stamp.read_text().strip() == brief_hash:
            return False
    with contextlib.suppress(OSError):
        stamp.write_text(brief_hash)
    return True


def _consecutive_run_cap(max_runs: int = 3, window_s: int = 600) -> bool:
    """Refuse if too many runs were triggered in the last window without a fresh image.

    Returns True if we should PROCEED, False if the cap is exceeded.
    Resets the counter when called with a fresh user image (not iterate).
    """
    log_file = Path("/tmp/styleforge_helper_run_count.log")
    now = time.time()
    cutoff = now - window_s
    timestamps: list[float] = []
    with contextlib.suppress(OSError):
        if log_file.is_file():
            timestamps = [
                float(line.strip())
                for line in log_file.read_text().splitlines()
                if line.strip() and float(line.strip()) > cutoff
            ]
    if len(timestamps) >= max_runs:
        return False
    timestamps.append(now)
    with contextlib.suppress(OSError):
        log_file.write_text("\n".join(str(t) for t in timestamps[-max_runs * 2 :]))
    return True


def _consume_inbound_images(images: list[Path]) -> None:
    """Move used inbound images to the archive so they can't be re-picked (CP-020)."""
    if not INBOUND_DIR:
        return
    archive = INBOUND_DIR.parent / "inbound.archive"
    with contextlib.suppress(OSError):
        archive.mkdir(parents=True, exist_ok=True)
        for img in images:
            shutil.move(str(img), str(archive / img.name))


def main() -> int:
    brief = sys.argv[1].strip() if len(sys.argv) >= 2 and sys.argv[1].strip() else ""
    assets = sys.argv[2].strip() if len(sys.argv) >= 3 and sys.argv[2].strip() else DEFAULT_ASSETS
    if not brief:
        print(
            "ERROR: 请提供一句话品牌简介（作为第一个参数）。"
            " 例如：一家温暖的手工小批量咖啡烘焙品牌。",
            file=sys.stderr,
        )
        return 1

    # Agent self-loop guard: if a run was started very recently, skip this
    # invocation to avoid the bot spamming duplicate kits when the agent
    # echoes its own output back as a new user message.
    if not _debounce_lock():
        log("skipped: another run was started < 180s ago (self-loop guard)")
        print("⏳ 上一轮生成刚完成，请稍等片刻再发送新消息。", flush=True)
        return 0

    # Brief dedup: if the agent echoes its own output verbatim, skip.
    if not _brief_dedup(brief):
        log("skipped: brief identical to last invocation (self-echo guard)")
        print("⏳ 检测到重复请求，请发送新的内容。", flush=True)
        return 0

    log(f"OPENCLAW_HOME = {OPENCLAW_HOME or '<unset>'}")
    log(f"API           = {API}")

    # Explicit image path (env) wins; else auto-discover OpenClaw inbound.
    # CP-020: support multiple reference images (comma-separated env or N inbound).
    explicit = os.environ.get("STYLEFORGE_IMAGE", "").strip()
    images: list[Path] = []
    if explicit:
        for part in explicit.split(","):
            p = part.strip()
            if p and Path(p).is_file():
                images.append(Path(p).resolve())
    if not images:
        images = latest_inbound_images(max_n=5)

    # CP-019: conversational iteration — if no image but there's a recent
    # completed run, treat the brief as iteration feedback.
    is_iterate = False
    if not images:
        prev_id = find_latest_assembled_run()
        if prev_id:
            log(f"no image — iterating on prev run {prev_id} with feedback: {brief[:80]}")
            is_iterate = True
        else:
            print(
                "ERROR: 没有找到参考图，也没有可迭代的历史 run。"
                "请先在对话里附一张参考图开始新的品牌生成。",
                file=sys.stderr,
            )
            return 1
    else:
        log(f"reference images -> {[str(p) for p in images]}")

    # Consecutive run cap: refuse if too many runs in the last 10 min
    # without a fresh user image (agent self-loop at slower rate).
    if not _consecutive_run_cap():
        log("skipped: consecutive run cap exceeded (3 runs / 10 min)")
        print("⏳ 近期生成次数过多，请稍后再试。", flush=True)
        return 0

    brand_name = derive_brand_name(brief)
    log(f"brand_name = {brand_name!r}, assets = {assets!r}, iterate={is_iterate}")

    # Health-check the orchestrator (quiet — not shown to user).
    with contextlib.suppress(Exception):
        _http_json(urllib.request.Request(f"{API}/api/health", method="GET"))

    if is_iterate:
        key_log(f"迭代模式：基于上一轮 {prev_id} 微调设计…")
        run_id = post_iterate(prev_id, brief)
    else:
        key_log("开始生成品牌视觉识别包…")
        # Consume the inbound images so a self-loop can't re-pick them.
        _consume_inbound_images(images)
        run_id = post_run(brief, images, brand_name, assets)
    key_log(f"Run {run_id} 已启动，等待流水线完成…")

    manifest = poll_until_assembled(run_id)
    status = manifest.get("status", "unknown")
    asset_rows = manifest.get("assets", []) or []
    approved = [a for a in asset_rows if a.get("status") == "approved"]
    failed = [a for a in asset_rows if a.get("status") == "failed"]
    palette = manifest.get("palette", []) or []
    log(f"assembled: status={status}, approved={len(approved)}, failed={len(failed)}")
    if approved:
        key_log(f"✅ {len(approved)} 项资产通过 Critic 评审")
    if failed:
        key_log(f"⚠️ {len(failed)} 项资产未通过，已在打磨中")

    media_lines: list[str] = []
    for a in approved:
        aid = str(a.get("id", "")).strip()
        if not aid:
            continue
        try:
            png = download_bytes(f"{API}/api/runs/{run_id}/kit/{aid}.png")
            dst = publish(f"{aid}.png", run_id, png)
            media_lines.append(f"MEDIA:{dst}")
            log(f"published {aid}.png -> {dst}")
        except Exception as exc:  # noqa: BLE001
            log(f"could not publish {aid}.png: {exc}")

    guide_path = ""
    guide_text = fetch_brand_guide(run_id)
    if guide_text:
        gp = publish("brand_guide.md", run_id, guide_text.encode("utf-8"))
        guide_path = str(gp)
        log(f"published brand_guide.md -> {gp}")

    # ---- deliver assets + descriptions directly to Telegram (if token set) ----
    deliver_to_telegram(approved, run_id, palette, guide_text)

    # ---- stdout: only MEDIA: lines + Brand guide: line (per SKILL.md rules) ----
    for line in media_lines:
        print(line, flush=True)
    if guide_path:
        print(f"Brand guide: {guide_path}", flush=True)
    elif not media_lines:
        print("生成失败：本次没有资产通过 Critic，请换个参考图或调整简介后重试。", flush=True)
        return 1

    # terse stderr summary (not shown to user per SKILL.md)
    log(
        f"done: {len(media_lines)} approved assets, "
        f"palette={palette}, failed={[a.get('id') for a in failed]}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
