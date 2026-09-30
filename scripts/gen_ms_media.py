"""用魔搭 API-Inference 生成 90s 演示素材（扣魔粒）。

图：POST /v1/images/generations + GET /v1/tasks/{id}（头 X-ModelScope-Task-Type: image_generation）
视频：Wan2.2-I2V（失败可跳过，用帧图+录屏）。
密钥只读 .env，不打印。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "media"
BASE = "https://api-inference.modelscope.cn/v1"

PROMPTS = [
    {
        "id": "frame01-hero",
        "prompt": (
            "Clean product UI mockup of TradePilot foreign-trade AI dashboard, "
            "teal and slate palette, wide 16:9, shipping documents on screen, "
            "no logos of real brands, no readable tiny text, cinematic lighting"
        ),
    },
    {
        "id": "frame02-pipeline",
        "prompt": (
            "Abstract isometric pipeline: purchase order document transforming into "
            "sales contract and shipping pack list, soft teal glow, professional B2B style, 16:9"
        ),
    },
    {
        "id": "frame03-check",
        "prompt": (
            "Close-up of consistency check UI with green pass marks on amount quantity Incoterms, "
            "minimal SaaS interface, teal accent, 16:9, no trademarks"
        ),
    },
]


def _key() -> str:
    vals = dotenv_values(ROOT / ".env")
    key = (
        vals.get("MODELSCOPE_API_KEY")
        or vals.get("LLM_API_KEY")
        or os.getenv("MODELSCOPE_API_KEY")
        or ""
    ).strip()
    if not key:
        raise SystemExit("缺少 MODELSCOPE_API_KEY — 请写入 tradepilot-app/.env")
    return key


def poll_image(client: httpx.Client, key: str, task_id: str, *, rounds: int = 90) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {key}",
        "X-ModelScope-Task-Type": "image_generation",
    }
    for i in range(rounds):
        time.sleep(5)
        st = client.get(f"{BASE}/tasks/{task_id}", headers=headers, timeout=60)
        if st.status_code != 200:
            print(f"  poll {i} HTTP {st.status_code}")
            continue
        js = st.json()
        status = str(js.get("task_status") or "").upper()
        print(f"  poll {i} status={status}")
        if status in {"SUCCEED", "SUCCEEDED", "FAILED", "ERROR"}:
            return js
    return {}


def poll_video(client: httpx.Client, key: str, task_id: str, *, rounds: int = 90) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {key}",
        "X-ModelScope-Task-Type": "video_generation",
    }
    for i in range(rounds):
        time.sleep(5)
        st = client.get(f"{BASE}/tasks/{task_id}", headers=headers, timeout=60)
        if st.status_code != 200:
            print(f"  poll-v {i} HTTP {st.status_code}")
            continue
        js = st.json()
        status = str(js.get("task_status") or "").upper()
        print(f"  poll-v {i} status={status}")
        if status in {"SUCCEED", "SUCCEEDED", "FAILED", "ERROR"}:
            return js
    return {}


def save_from_task(client: httpx.Client, js: dict[str, Any], out_path: Path) -> bool:
    urls = js.get("output_images") or js.get("output_videos") or []
    if not urls:
        outs = js.get("outputs")
        if isinstance(outs, dict):
            urls = outs.get("output_images") or outs.get("output_videos") or outs.get("images") or []
        elif isinstance(outs, list):
            urls = [x for x in outs if isinstance(x, str) and x.startswith("http")]
    if not urls:
        print("no urls", list(js.keys()), (json.dumps(js)[:400]))
        return False
    blob = client.get(urls[0], timeout=180)
    blob.raise_for_status()
    out_path.write_bytes(blob.content)
    print(f"saved {out_path} bytes={len(blob.content)}")
    return True


def gen_image(client: httpx.Client, key: str, prompt: str, out_path: Path) -> bool:
    r = client.post(
        f"{BASE}/images/generations",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-ModelScope-Async-Mode": "true",
        },
        json={"model": "Qwen/Qwen-Image", "prompt": prompt, "size": "1280x720"},
        timeout=120,
    )
    print(f"image submit HTTP {r.status_code} -> {out_path.name}")
    if r.status_code == 429:
        print("rate limited; wait 30s")
        time.sleep(30)
        return False
    if r.status_code != 200:
        print((r.text or "")[:300])
        return False
    tid = r.json().get("task_id")
    if not tid:
        return False
    # 注意：submit 体里的 task_status=SUCCEED 只表示受理，真正结果靠轮询
    js = poll_image(client, key, tid)
    status = str(js.get("task_status") or "").upper()
    if status not in {"SUCCEED", "SUCCEEDED"}:
        print("image not ready", status, (json.dumps(js)[:300]))
        return False
    return save_from_task(client, js, out_path)


def gen_video(client: httpx.Client, key: str, prompt: str, image_path: Path, out_mp4: Path) -> bool:
    import base64

    data_url = "data:image/png;base64," + base64.b64encode(image_path.read_bytes()).decode("ascii")
    r = client.post(
        f"{BASE}/videos/generations",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-ModelScope-Async-Mode": "true",
        },
        json={
            "model": "Wan-AI/Wan2.2-I2V-A14B",
            "prompt": prompt,
            "image_url": data_url,
            "size": "1280*720",
            "duration": 5,
        },
        timeout=120,
    )
    print(f"video submit HTTP {r.status_code}")
    if r.status_code != 200:
        print((r.text or "")[:300])
        return False
    tid = r.json().get("task_id")
    if not tid:
        print((r.text or "")[:300])
        return False
    js = poll_video(client, key, tid)
    status = str(js.get("task_status") or "").upper()
    if status not in {"SUCCEED", "SUCCEEDED"}:
        print("video not ready / provider issue", status, (json.dumps(js)[:300]))
        return False
    return save_from_task(client, js, out_mp4)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    key = _key()
    ok_imgs = 0
    paths: list[Path] = []
    with httpx.Client() as client:
        for i, item in enumerate(PROMPTS):
            if i:
                time.sleep(10)
            path = OUT / f"{item['id']}.png"
            if gen_image(client, key, item["prompt"], path):
                ok_imgs += 1
                paths.append(path)
                (OUT / f"{item['id']}.json").write_text(
                    json.dumps(
                        {"model": "Qwen/Qwen-Image", "prompt": item["prompt"]},
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
        video_ok = False
        if paths:
            video_ok = gen_video(
                client,
                key,
                "Slow camera push-in on a modern trade operations dashboard",
                paths[0],
                OUT / "intro-5s-wan.mp4",
            )
    manifest = {
        "images_ok": ok_imgs,
        "video_ok": video_ok,
        "note": "submit 的 SUCCEED≠出图完成；须带 X-ModelScope-Task-Type 轮询。排队久可稍后重跑。",
        "out_dir": str(OUT),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("MANIFEST", json.dumps(manifest, ensure_ascii=False))
    return 0 if ok_imgs else 2


if __name__ == "__main__":
    sys.exit(main())
