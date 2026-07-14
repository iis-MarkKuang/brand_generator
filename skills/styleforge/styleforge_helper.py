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
  styleforge_helper.py "warm craft coffee roaster" "logo,social_square,hero_banner"

Environment:
  OPENCLAW_HOME     — OpenClaw home (media/workspace boundary)
  STYLEFORGE_API    — orchestrator base URL (default http://127.0.0.1:8000)
"""

from __future__ import annotations

import io
import json
import mimetypes
import os
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
DEFAULT_ASSETS = "logo,social_square,hero_banner"
POLL_INTERVAL_S = 4
POLL_TIMEOUT_S = 480  # 8 min ceiling for a chat turn


def log(msg: str) -> None:
    print(f"[styleforge] {msg}", file=sys.stderr, flush=True)


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


def latest_inbound_image() -> Path | None:
    """Newest image in OpenClaw's inbound boundary (workshop convention)."""
    if not INBOUND_DIR or not INBOUND_DIR.is_dir():
        return None
    candidates = [
        p
        for p in INBOUND_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def derive_brand_name(brief: str) -> str:
    words = [w for w in brief.replace(",", " ").split() if w]
    if not words:
        return "Untitled"
    name = " ".join(words[:3])
    return name[:40]


def post_run(brief: str, image_path: Path, brand_name: str, assets: str) -> str:
    """multipart/form-data POST to /api/runs → run_id (stdlib only)."""
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
    # image file part
    mime = mimetypes.guess_type(str(image_path))[0] or "image/png"
    fname = image_path.name
    buf.write(f"--{boundary}\r\n".encode())
    buf.write(f'Content-Disposition: form-data; name="image"; filename="{fname}"\r\n'.encode())
    buf.write(f"Content-Type: {mime}\r\n\r\n".encode())
    buf.write(image_path.read_bytes())
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
            log(f"stage: {stage}")
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
TG_TOKEN = os.environ.get("STYLEFORGE_TG_TOKEN", "").strip()
TG_CHAT = os.environ.get("STYLEFORGE_TG_CHAT", "").strip().split(",")[0].strip()
TG_API = "https://api.telegram.org"


def _tg_post(endpoint: str, fields: list[tuple[str, str]], photo: bytes | None = None,
             photo_fname: str = "asset.png") -> dict:
    """POST to Telegram Bot API (stdlib multipart). Returns parsed JSON."""
    boundary = f"----tg{uuid4().hex}"
    buf = io.BytesIO()
    for key, val in fields:
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        buf.write(f"{val}\r\n".encode())
    if photo is not None:
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(f'Content-Disposition: form-data; name="photo"; filename="{photo_fname}"\r\n'.encode())
        buf.write(b"Content-Type: image/png\r\n\r\n")
        buf.write(photo)
        buf.write(b"\r\n")
    buf.write(f"--{boundary}--\r\n".encode())
    body = buf.getvalue()
    req = urllib.request.Request(
        f"{TG_API}/bot{TG_TOKEN}/{endpoint}",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
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
        _tg_post("sendPhoto", [("chat_id", TG_CHAT), ("caption", caption[:1024])],
                 photo=image, photo_fname="brand_asset.png")
        log(f"telegram photo sent ({len(image)} bytes, caption {len(caption)} chars)")
    except Exception as exc:  # noqa: BLE001
        log(f"telegram photo send failed: {exc}")


def deliver_to_telegram(approved: list, run_id: str, palette: list, brand_guide: str) -> None:
    """Send each approved asset as a Telegram photo + a summary text message."""
    if not TG_TOKEN or not TG_CHAT:
        log("telegram delivery skipped (no STYLEFORGE_TG_TOKEN / chat id)")
        return
    labels = {"logo": "Logo", "social_square": "Social Square", "hero_banner": "Hero Banner"}
    sent = 0
    for a in approved:
        aid = str(a.get("id", "")).strip()
        if not aid:
            continue
        try:
            png = download_bytes(f"{API}/api/runs/{run_id}/kit/{aid}.png")
            label = labels.get(aid, aid)
            score = a.get("score", "?")
            caption = f"🎨 {label} (score: {score}/100) — approved by Critic"
            send_telegram_photo(png, caption)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            log(f"could not send {aid} to telegram: {exc}")

    # Summary message with palette + brand guide excerpt
    palette_parts = []
    for p in palette[:4]:
        if isinstance(p, dict):
            palette_parts.append(f"{p.get('name', '')} {p.get('hex', '')}")
        else:
            palette_parts.append(str(p))
    palette_str = " / ".join(palette_parts)
    guide_excerpt = brand_guide[:800] if brand_guide else ""
    summary = (
        f"✅ StyleForge Brand Kit Complete\n"
        f"{sent} assets delivered\n\n"
        f"Palette: {palette_str}\n\n"
    )
    if guide_excerpt:
        summary += f"Brand Guide (excerpt):\n{guide_excerpt}\n"
    summary += f"\nRun ID: {run_id}"
    send_telegram_text(summary)


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

    log(f"OPENCLAW_HOME = {OPENCLAW_HOME or '<unset>'}")
    log(f"API           = {API}")

    # Explicit image path (env) wins; else auto-discover OpenClaw inbound.
    explicit = os.environ.get("STYLEFORGE_IMAGE", "").strip()
    if explicit and Path(explicit).is_file():
        image = Path(explicit).resolve()
    else:
        image = latest_inbound_image()
    if image is None:
        print(
            "ERROR: 没有找到参考图。请先在对话里附一张参考图。",
            file=sys.stderr,
        )
        return 1
    log(f"reference image -> {image}")

    brand_name = derive_brand_name(brief)
    log(f"brand_name = {brand_name!r}, assets = {assets!r}")

    # Health-check the orchestrator (helpful, not fatal).
    try:
        h = _http_json(urllib.request.Request(f"{API}/api/health", method="GET"))
        log(f"orchestrator health: {h}")
    except Exception as exc:  # noqa: BLE001
        log(f"orchestrator health check failed: {exc}")

    log("POST /api/runs …")
    run_id = post_run(brief, image, brand_name, assets)
    log(f"run_id = {run_id}, polling until assembled (~{POLL_TIMEOUT_S}s ceiling)")

    manifest = poll_until_assembled(run_id)
    status = manifest.get("status", "unknown")
    asset_rows = manifest.get("assets", []) or []
    approved = [a for a in asset_rows if a.get("status") == "approved"]
    failed = [a for a in asset_rows if a.get("status") == "failed"]
    palette = manifest.get("palette", []) or []
    log(f"assembled: status={status}, approved={len(approved)}, failed={len(failed)}")

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
