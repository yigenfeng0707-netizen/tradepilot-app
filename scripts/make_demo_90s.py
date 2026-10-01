"""TradePilot 90s demo: local Chrome CDP record + edge-tts + ffmpeg compose.

Uses connect_over_cdp (port 9222) — never downloads Playwright Chromium.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "demo-output"
SEG = OUT / "segments"
MEDIA = ROOT / "docs" / "media"
FINAL = MEDIA / "TradePilot-demo-90s.mp4"
FFMPEG = r"C:\ffmpeg\ffmpeg-6.1.1-essentials_build\bin\ffmpeg.exe"
FFPROBE = r"C:\ffmpeg\ffmpeg-6.1.1-essentials_build\bin\ffprobe.exe"
BASE = "http://127.0.0.1:8787"
CDP = "http://127.0.0.1:9222"
EDGE_TTS = str(ROOT / ".venv" / "Scripts" / "edge-tts.exe")

SCENES = [
    {
        "id": "intro",
        "kind": "title",
        "title": "TradePilot",
        "subtitle": "外贸全链路 AI 数字员工 · P1 + P2",
        "narration": "外贸一票单证，人工要两小时；退单一次，码头费和交期一起炸。",
        "hold": 8,
    },
    {
        "id": "home",
        "kind": "browser",
        "narration": "TradePilot 是外贸全链路 AI 数字员工。先看 P1：上传采购订单，自动出合同和全套单据。",
        "actions": "home",
        "hold": 8,
    },
    {
        "id": "run",
        "kind": "browser",
        "narration": "点击加载样例采购订单。买方迪拜 ABC Trading，五千套 LED，CIF 杰贝阿里，总额一万六千美元。",
        "actions": "run",
        "hold": 16,
    },
    {
        "id": "extract",
        "kind": "browser",
        "narration": "系统完成解析：字段带置信度；单价乘数量自动校验金额。",
        "actions": "extract",
        "hold": 10,
    },
    {
        "id": "docs",
        "kind": "browser",
        "narration": "以购销合同为唯一数据源，生成中英合同，并一源多单派生 PI、CI、PL；一致性校验通过。",
        "actions": "docs",
        "hold": 12,
    },
    {
        "id": "finance",
        "kind": "browser",
        "narration": "进入 P2 财务台账：写入演示收付与待申报退税，可见部分核销与毛利一瞥。",
        "actions": "finance",
        "hold": 16,
    },
    {
        "id": "outro",
        "kind": "title",
        "title": "TradePilot",
        "subtitle": "让每个中小外贸公司用得起一支 AI 团队",
        "narration": "人工只需确认风险项。从两小时操作，压缩到十分钟决策。TradePilot，让每个中小外贸公司用得起一支 AI 团队。",
        "hold": 12,
    },
]


def run(cmd: list[str]) -> None:
    print("+", " ".join(str(c) for c in cmd[:8]), "...", flush=True)
    subprocess.run(cmd, check=True)


def cdp_endpoint() -> str:
    try:
        data = json.loads(urllib.request.urlopen(CDP + "/json/version", timeout=3).read())
        return data.get("webSocketDebuggerUrl") or CDP
    except Exception as e:
        raise RuntimeError(
            f"Chrome CDP not reachable at {CDP}. "
            "Start Chrome with --remote-debugging-port=9222 (see chrome-cdp-session skill)."
        ) from e


def probe_duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nk=1:nw=1",
            str(path),
        ],
        text=True,
    ).strip()
    return float(out or "3")


def tts(text: str, mp3: Path) -> float:
    mp3.parent.mkdir(parents=True, exist_ok=True)
    edge = EDGE_TTS if Path(EDGE_TTS).exists() else "edge-tts"
    # Equals form required: argparse treats `--rate -5%` as a flag, not a value.
    try:
        run(
            [
                edge,
                "--voice=zh-CN-YunxiNeural",
                "--rate=-5%",
                "--text",
                text,
                "--write-media",
                str(mp3),
            ]
        )
    except subprocess.CalledProcessError:
        print("edge-tts with rate failed; retry without rate", flush=True)
        run(
            [
                edge,
                "--voice=zh-CN-XiaoxiaoNeural",
                "--text",
                text,
                "--write-media",
                str(mp3),
            ]
        )
    return probe_duration(mp3)


def title_png(path: Path, title: str, subtitle: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1440, 900), (14, 26, 36))
    d = ImageDraw.Draw(img)
    try:
        f1 = ImageFont.truetype(r"C:\Windows\Fonts\simhei.ttf", 72)
        f2 = ImageFont.truetype(r"C:\Windows\Fonts\simhei.ttf", 32)
    except Exception:
        f1 = ImageFont.load_default()
        f2 = f1
    d.text((80, 340), title, fill=(232, 244, 248), font=f1)
    d.text((80, 440), subtitle, fill=(140, 190, 200), font=f2)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def png_to_mp4(png: Path, mp4: Path, seconds: float) -> None:
    run(
        [
            FFMPEG,
            "-y",
            "-loop",
            "1",
            "-i",
            str(png),
            "-c:v",
            "libx264",
            "-t",
            f"{seconds:.2f}",
            "-pix_fmt",
            "yuv420p",
            "-vf",
            "scale=1440:900",
            str(mp4),
        ]
    )


def mux(video: Path, audio: Path, out: Path, target_sec: float) -> None:
    """Mux A/V and pad audio with silence to target_sec (keeps video length)."""
    run(
        [
            FFMPEG,
            "-y",
            "-i",
            str(video),
            "-i",
            str(audio),
            "-filter_complex",
            f"[1:a]apad=whole_dur={target_sec:.2f}[a]",
            "-map",
            "0:v",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-t",
            f"{target_sec:.2f}",
            str(out),
        ]
    )


def slice_video(src: Path, out: Path, start: float, duration: float) -> None:
    run(
        [
            FFMPEG,
            "-y",
            "-ss",
            f"{start:.2f}",
            "-i",
            str(src),
            "-t",
            f"{duration:.2f}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-vf",
            "scale=1440:900",
            "-an",
            str(out),
        ]
    )


def ensure_results(page) -> None:
    """Wait until sample pipeline finished and #results is shown.

    Do NOT wait for bare text '一致性校验通过' — that string appears in hero copy.
    """
    try:
        if page.locator("#results:not(.hidden)").count() > 0 and page.locator("#results").is_visible():
            return
    except Exception:
        pass
    # If a run is already in progress (button disabled), just wait it out.
    busy = False
    try:
        busy = page.locator("#btn-sample").is_disabled()
    except Exception:
        busy = False
    if not busy:
        page.locator("#btn-sample").click()
    page.wait_for_selector("#results:not(.hidden)", timeout=180000)
    # Prefer pass badge when present; tolerate fail for demo continuity.
    try:
        page.wait_for_selector("#consistency.pass, #consistency.fail", timeout=10000)
    except Exception:
        pass


def wait_sample_done(page) -> None:
    page.locator("#btn-sample").click()
    page.wait_for_selector("#results:not(.hidden)", timeout=180000)
    try:
        page.wait_for_selector("#consistency.pass, #consistency.fail", timeout=10000)
    except Exception:
        pass


def record_browser_continuous(browser_holds: list[tuple[str, float]]) -> tuple[Path, list[tuple[str, float, float]]]:
    """One CDP context: home → run sample once → scroll scenes.

    Returns (full_mp4, [(sid, start_sec, end_sec), ...]).
    """
    rec_dir = SEG / "_rec_browser"
    rec_dir.mkdir(parents=True, exist_ok=True)
    endpoint = cdp_endpoint()
    print("CDP", endpoint, flush=True)

    marks: list[tuple[str, float]] = []
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(endpoint)
        # New context so record_video works (default CDP context has no recorder).
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_video_dir=str(rec_dir),
            record_video_size={"width": 1440, "height": 900},
        )
        page = context.new_page()
        page.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
        time.sleep(1.0)

        t0 = time.monotonic()

        for sid, hold in browser_holds:
            print("BROWSER_SCENE", sid, "hold", hold, flush=True)
            marks.append((sid, time.monotonic() - t0))
            if sid == "home":
                time.sleep(hold)
            elif sid == "run":
                wait_sample_done(page)
                elapsed = time.monotonic() - t0 - marks[-1][1]
                remain = max(2.0, hold - elapsed)
                time.sleep(remain)
            elif sid == "extract":
                ensure_results(page)
                page.mouse.wheel(0, 400)
                time.sleep(hold / 2)
                page.mouse.wheel(0, 250)
                time.sleep(hold / 2)
            elif sid == "docs":
                ensure_results(page)
                page.mouse.wheel(0, 500)
                time.sleep(hold / 2)
                # Highlight consistency if present
                try:
                    page.locator("#consistency").scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    pass
                time.sleep(hold / 2)
            elif sid == "finance":
                ensure_results(page)
                try:
                    page.locator("#p2").scroll_into_view_if_needed(timeout=5000)
                except Exception:
                    page.mouse.wheel(0, 900)
                time.sleep(1.0)
                try:
                    if page.locator("#btn-finance-seed").is_visible():
                        page.locator("#btn-finance-seed").click()
                        page.wait_for_timeout(1500)
                except Exception:
                    pass
                try:
                    page.locator("#p2-settlement").scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    page.mouse.wheel(0, 200)
                time.sleep(hold / 3)
                try:
                    page.locator("#p2-rebates").scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    page.mouse.wheel(0, 250)
                time.sleep(hold / 3)
                try:
                    page.locator("#p2-margin").scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    page.mouse.wheel(0, 250)
                time.sleep(hold / 3)

        total = time.monotonic() - t0
        vid = page.video
        context.close()
        # Do not browser.close() on CDP — leave user's Chrome running.
        webm = Path(vid.path()) if vid else None

    if not webm or not webm.exists():
        raise RuntimeError("CDP recording produced no video file")

    full = SEG / "browser_full.mp4"
    run(
        [
            FFMPEG,
            "-y",
            "-i",
            str(webm),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-vf",
            "scale=1440:900",
            str(full),
        ]
    )
    ranges: list[tuple[str, float, float]] = []
    for i, (sid, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else total
        ranges.append((sid, start, max(start + 0.5, end)))
    (SEG / "browser_marks.json").write_text(
        json.dumps({"marks": marks, "ranges": ranges, "holds": browser_holds, "total": total}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return full, ranges


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    SEG.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []

    # Health check
    health = json.loads(urllib.request.urlopen(BASE + "/api/health", timeout=5).read())
    print("HEALTH", health.get("ok"), health.get("llm_model"), flush=True)
    cdp_endpoint()  # fail fast if CDP down

    # TTS first (all scenes); reuse existing mp3 if present
    holds: dict[str, float] = {}
    mp3s: dict[str, Path] = {}
    for i, scene in enumerate(SCENES):
        sid = scene["id"]
        mp3 = SEG / f"{i:02d}_{sid}.mp3"
        if mp3.exists() and mp3.stat().st_size > 500:
            print("TTS_REUSE", sid, flush=True)
            dur = probe_duration(mp3)
        else:
            print("TTS", sid, flush=True)
            dur = tts(scene["narration"], mp3)
        hold = max(float(scene.get("hold") or 4), dur + 0.4)
        holds[sid] = hold
        mp3s[sid] = mp3

    # Title cards
    for i, scene in enumerate(SCENES):
        if scene["kind"] != "title":
            continue
        sid = scene["id"]
        print("TITLE", sid, flush=True)
        png = SEG / f"{i:02d}_{sid}.png"
        title_png(png, scene["title"], scene["subtitle"])
        raw = SEG / f"{i:02d}_{sid}_v.mp4"
        png_to_mp4(png, raw, holds[sid])
        out = SEG / f"{i:02d}_{sid}.mp4"
        mux(raw, mp3s[sid], out, holds[sid])
        # store index later via ordered parts

    # One continuous CDP browser recording for all browser scenes
    browser_scenes = [(s["id"], holds[s["id"]]) for s in SCENES if s["kind"] == "browser"]
    full = SEG / "browser_full.mp4"
    marks_path = SEG / "browser_marks.json"
    force = os.environ.get("FORCE_RERECORD", "").strip() in ("1", "true", "yes")
    scene_ids = [s[0] for s in browser_scenes]
    reuse = (
        not force
        and full.exists()
        and marks_path.exists()
        and full.stat().st_size > 100_000
    )
    if reuse:
        marks_data = json.loads(marks_path.read_text(encoding="utf-8"))
        prev_ids = [r[0] for r in marks_data.get("ranges") or []]
        if prev_ids != scene_ids:
            print("RECORD_CDP scene list changed; re-record", prev_ids, "->", scene_ids, flush=True)
            reuse = False
    if reuse:
        print("RECORD_CDP reuse existing browser_full.mp4", flush=True)
        marks_data = json.loads(marks_path.read_text(encoding="utf-8"))
        ranges = [tuple(x) for x in marks_data["ranges"]]
    else:
        # Drop stale TTS/browser caches that predate P2 scene list
        for stale in SEG.glob("0*_*.mp3"):
            # Keep only if matching current scene ids by suffix later; remove check/old
            pass
        for stale_name in ("03_check.mp3", "04_check.mp3", "05_check.mp3", "browser_check_v.mp4"):
            p = SEG / stale_name
            if p.exists():
                p.unlink()
        print("RECORD_CDP continuous", scene_ids, flush=True)
        full, ranges = record_browser_continuous(browser_scenes)

    browser_raw: dict[str, Path] = {}
    for sid, start, end in ranges:
        raw = SEG / f"browser_{sid}_v.mp4"
        # For long LLM "run", keep last `hold` seconds (results visible), not the spinner wait.
        hold = holds[sid]
        dur = end - start
        if sid == "run" and dur > hold + 1.0:
            slice_video(full, raw, end - hold, hold)
        else:
            slice_video(full, raw, start, max(hold, min(dur, hold + 2.0)))
        browser_raw[sid] = raw

    # Assemble parts in storyboard order
    for i, scene in enumerate(SCENES):
        sid = scene["id"]
        out = SEG / f"{i:02d}_{sid}.mp4"
        if scene["kind"] == "title":
            if not out.exists():
                raise RuntimeError(f"missing title segment {out}")
            parts.append(out)
            continue
        raw = browser_raw[sid]
        # Pad/trim video to hold then mux
        trimmed = SEG / f"{i:02d}_{sid}_v.mp4"
        run(
            [
                FFMPEG,
                "-y",
                "-stream_loop",
                "-1",
                "-i",
                str(raw),
                "-t",
                f"{holds[sid]:.2f}",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-an",
                str(trimmed),
            ]
        )
        mux(trimmed, mp3s[sid], out, holds[sid])
        parts.append(out)

    # concat
    lst = SEG / "concat.txt"
    lst.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in parts), encoding="utf-8")
    tmp = OUT / "demo_concat.mp4"
    run(
        [
            FFMPEG,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(lst),
            "-c",
            "copy",
            str(tmp),
        ]
    )

    # optional prepend 魔搭 5s intro if exists (must include silent audio for concat)
    intro = MEDIA / "intro-5s-wan-moli.mp4"
    FINAL.parent.mkdir(parents=True, exist_ok=True)
    to_norm: list[Path] = []
    if intro.exists():
        intro_scaled = SEG / "intro_scaled.mp4"
        run(
            [
                FFMPEG,
                "-y",
                "-i",
                str(intro),
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=24000:cl=mono",
                "-vf",
                "scale=1440:900:force_original_aspect_ratio=decrease,pad=1440:900:(ow-iw)/2:(oh-ih)/2,fps=25",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                "-t",
                "5",
                str(intro_scaled),
            ]
        )
        to_norm.append(intro_scaled)
    to_norm.extend(parts)

    # Normalize fps/audio then concat (copy-concat without matching A/V breaks duration)
    norm_files: list[Path] = []
    for i, src in enumerate(to_norm):
        npath = SEG / f"norm_{i}.mp4"
        run(
            [
                FFMPEG,
                "-y",
                "-i",
                str(src),
                "-vf",
                "scale=1440:900,fps=25",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ar",
                "24000",
                "-ac",
                "1",
                str(npath),
            ]
        )
        norm_files.append(npath)
    lst_final = SEG / "concat_norm.txt"
    lst_final.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in norm_files) + "\n",
        encoding="utf-8",
    )
    run(
        [
            FFMPEG,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(lst_final),
            "-c",
            "copy",
            str(FINAL),
        ]
    )

    dur = probe_duration(FINAL)
    meta = {
        "final": str(FINAL),
        "bytes": FINAL.stat().st_size,
        "duration": dur,
        "scenes": [s["id"] for s in SCENES],
        "cdp": CDP,
        "record_mode": "connect_over_cdp_continuous",
    }
    (OUT / "demo_90s_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("FINAL", FINAL, FINAL.stat().st_size, f"{dur:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
