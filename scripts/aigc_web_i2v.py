"""通道 A：网页 AIGC 图生视频（扣魔粒）。监听网络拿真实成片 URL，不误下封面预览。"""
from __future__ import annotations

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "media"
FRAME = OUT / "frame-hero-moli.png"
if not FRAME.exists():
    FRAME = OUT / "frame01-hero.png"
PROMPT = (
    "Slow cinematic camera push-in on a modern teal SaaS trade dashboard, "
    "subtle UI motion, professional product demo"
)


def main() -> int:
    found: dict = {"task_id": None, "video_url": None, "submit": None, "status_payloads": []}

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        ctx = browser.contexts[0]
        page = next((pg for pg in ctx.pages if "modelscope.cn" in (pg.url or "")), None)
        if page is None:
            page = ctx.new_page()

        def on_response(resp):
            try:
                url = resp.url
                if "muse" not in url and "predict" not in url and "aigc" not in url:
                    return
                if resp.status >= 400:
                    return
                ct = (resp.headers.get("content-type") or "")
                if "json" not in ct:
                    return
                data = resp.json()
                text = json.dumps(data, ensure_ascii=False)
                if "taskId" in text or "task_id" in text:
                    found["submit"] = {"url": url, "data": data}
                    tid = (
                        (data.get("Data") or {}).get("data", {}).get("taskId")
                        if isinstance(data.get("Data"), dict)
                        else None
                    )
                    tid = tid or data.get("taskId") or data.get("task_id")
                    if isinstance(data.get("Data"), dict):
                        tid = tid or data["Data"].get("taskId") or (data["Data"].get("data") or {}).get("taskId")
                    if tid:
                        found["task_id"] = tid
                        print("NET_TASK", tid, url[-60:], flush=True)
                if any(k in text for k in ("SUCCESS", "SUCCEED", ".mp4", "outputUrl", "videoUrl")):
                    found["status_payloads"].append({"url": url, "data": data})
                    # dig url
                    blob = text
                    import re

                    m = re.search(r"https://[^\"'\\s]+\.mp4[^\"'\\s]*", blob)
                    if m and "cover-videos" not in m.group(0):
                        found["video_url"] = m.group(0)
                        print("NET_MP4", found["video_url"][:100], flush=True)
            except Exception:
                return

        page.on("response", on_response)
        page.goto(
            "https://www.modelscope.cn/aigc/video-generation",
            wait_until="domcontentloaded",
            timeout=120000,
        )
        time.sleep(4)

        moli = page.evaluate(
            """() => {
              const nodes=[...document.querySelectorAll('button')];
              for (const el of nodes) {
                const t=(el.innerText||'').trim();
                if (/^\\d{3,5}$/.test(t)) return t;
              }
              return null;
            }"""
        )
        print("MOLI_BALANCE", moli, flush=True)

        # 尝试切到 Wan（省积分）；失败则用当前 Checkpoint
        page.evaluate(
            """() => {
              const el=[...document.querySelectorAll('button,[role=button],div,span')]
                .find(e => (e.innerText||'').includes('模型管理') || (e.innerText||'').includes('Checkpoint'));
              if (el) el.click();
            }"""
        )
        time.sleep(1)
        page.evaluate(
            """() => {
              const el=[...document.querySelectorAll('div,button,span,li')]
                .find(e => /Wan2\\.2|Wan 2\\.2|图生视频/.test(e.innerText||''));
              if (el) el.click();
            }"""
        )
        time.sleep(1)

        page.locator('input[type="file"]').first.set_input_files(str(FRAME))
        print("UPLOADED", FRAME.name, flush=True)
        time.sleep(2)
        page.locator("textarea").first.fill(PROMPT)
        print("PROMPT_SET", flush=True)

        # 预计消耗
        cost = page.evaluate(
            """() => {
              const t=document.body.innerText||'';
              const m=t.match(/预计消耗魔粒值\\s*(\\d+)/) || t.match(/消耗魔粒[^\\d]*(\\d+)/);
              return m ? m[1] : null;
            }"""
        )
        print("EST_COST", cost, flush=True)

        page.evaluate(
            """() => {
              const labels=['添加AI标识并生成','生成视频','开始生成'];
              const btns=[...document.querySelectorAll('button,[role=button]')];
              for (const lab of labels) {
                const el=btns.find(b => (b.innerText||'').includes(lab));
                if (el) { el.click(); return lab; }
              }
              return null;
            }"""
        )
        time.sleep(2)
        page.evaluate(
            """() => {
              const labels=['添加AI标识并生成','确认生成','确认'];
              const btns=[...document.querySelectorAll('button,[role=button]')];
              for (const lab of labels) {
                const el=btns.find(b => (b.innerText||'').includes(lab));
                if (el) { el.click(); return lab; }
              }
              return null;
            }"""
        )
        print("SUBMITTED", "task", found.get("task_id"), flush=True)

        # 最长约 15 分钟
        for i in range(120):
            time.sleep(8)
            if found.get("video_url"):
                break
            # DOM 再扫一遍，排除 cover-videos
            urls = page.evaluate(
                """() => [...document.querySelectorAll('video,a')]
                  .map(el => el.src || el.href || '')
                  .filter(u => /\\.mp4/i.test(u) && !u.includes('cover-videos'))"""
            )
            print("poll", i, "task", found.get("task_id"), "dom_mp4", urls[:2], flush=True)
            if urls:
                found["video_url"] = urls[0]
                break
            # 点生成历史刷新
            if i % 5 == 4:
                page.evaluate(
                    """() => {
                      const el=[...document.querySelectorAll('button,[role=button],a')]
                        .find(b => (b.innerText||'').includes('生成历史'));
                      if (el) el.click();
                    }"""
                )

        if not found.get("video_url"):
            print("NO_REAL_VIDEO", json.dumps({k: found[k] for k in found if k != "status_payloads"}, ensure_ascii=False)[:500])
            page.screenshot(path=str(OUT / "aigc-video-wait.png"), full_page=True)
            (OUT / "aigc-video-debug.json").write_text(
                json.dumps(found, ensure_ascii=False, indent=2)[:20000], encoding="utf-8"
            )
            return 3

        url = found["video_url"]
        print("VIDEO_URL", url[:140], flush=True)
        out = OUT / "intro-5s-wan-moli.mp4"
        import httpx

        with httpx.Client(timeout=180, follow_redirects=True) as c:
            if url.startswith("blob:"):
                data = page.evaluate(
                    """async (u) => Array.from(new Uint8Array(await (await fetch(u)).arrayBuffer()))""",
                    url,
                )
                out.write_bytes(bytes(data))
            else:
                r = c.get(url)
                r.raise_for_status()
                out.write_bytes(r.content)
        print("SAVED", out, out.stat().st_size, flush=True)
        (OUT / "intro-5s-wan-moli.json").write_text(
            json.dumps(
                {
                    "channel": "A_web_aigc",
                    "moli_balance": moli,
                    "est_cost": cost,
                    "task_id": found.get("task_id"),
                    "source_frame": FRAME.name,
                    "bytes": out.stat().st_size,
                    "url_host": url.split("/")[2] if url.startswith("http") else "blob",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
