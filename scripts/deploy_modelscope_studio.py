"""Deploy deploy-studio/* to ModelScope Studio via Chrome CDP. Never print secrets."""
from __future__ import annotations

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OWNER = "gsym236998"
NAME = "tradepilot-demo"
ROOT = Path(__file__).resolve().parents[1] / "deploy-studio"
FILES = ["index.html"]  # Docker 创空间仅已有文件可 PUT；单文件内联 CSS/JS/样例


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        ctx = browser.contexts[0]
        page = next((pg for pg in ctx.pages if "modelscope.cn" in (pg.url or "")), None)
        if page is None:
            page = ctx.new_page()
        page.goto(
            f"https://www.modelscope.cn/studios/{OWNER}/{NAME}",
            wait_until="domcontentloaded",
            timeout=90000,
        )
        time.sleep(2)

        st = page.evaluate(
            """async ({ owner, name }) => {
              const res = await fetch(
                `https://www.modelscope.cn/api/v1/studio/${owner}/${name}`,
                { credentials: "include" }
              );
              const j = await res.json();
              const d = j.Data || {};
              return {
                http: res.status,
                code: j.Code,
                status: d.Status,
                url: d.IndependentUrl,
                message: j.Message || j.msg || "",
              };
            }""",
            {"owner": OWNER, "name": NAME},
        )
        print("studio_api", json.dumps(st, ensure_ascii=False))
        if st.get("http") in (401, 403) or "登录" in str(st.get("message") or ""):
            print("LOGIN_REQUIRED")
            return 2

        results = {}
        for fname in FILES:
            path = ROOT / fname
            content = path.read_text(encoding="utf-8")
            r = page.evaluate(
                """async ({ owner, name, filePath, content, message }) => {
                  const res = await fetch(
                    `https://www.modelscope.cn/api/v1/studio/${owner}/${name}/repo`,
                    {
                      method: "PUT",
                      credentials: "include",
                      headers: {
                        "Content-Type": "application/json",
                        Accept: "application/json",
                      },
                      body: JSON.stringify({
                        FilePath: filePath,
                        Revision: "master",
                        ReadMeContent: content,
                        CommitMessage: message,
                      }),
                    }
                  );
                  const text = await res.text();
                  return {
                    status: res.status,
                    ok: /"Code":200|"Success":true/i.test(text),
                    body: text.slice(0, 280),
                  };
                }""",
                {
                    "owner": OWNER,
                    "name": NAME,
                    "filePath": fname,
                    "content": content,
                    "message": f"deploy product demo: update {fname}",
                },
            )
            results[fname] = r
            print("PUT", fname, r.get("status"), r.get("ok"), (r.get("body") or "")[:160])

        deploy = page.evaluate(
            """async ({ owner, name }) => {
              const res = await fetch(
                `https://www.modelscope.cn/openapi/v1/studios/${owner}/${name}/deploy`,
                {
                  method: "POST",
                  credentials: "include",
                  headers: { Accept: "application/json" },
                }
              );
              return { status: res.status, body: (await res.text()).slice(0, 400) };
            }""",
            {"owner": OWNER, "name": NAME},
        )
        print("DEPLOY", deploy.get("status"), (deploy.get("body") or "")[:240])

        final = {}
        for i in range(48):
            time.sleep(5)
            st2 = page.evaluate(
                """async ({ owner, name }) => {
                  const j = await (
                    await fetch(
                      `https://www.modelscope.cn/api/v1/studio/${owner}/${name}`,
                      { credentials: "include" }
                    )
                  ).json();
                  const d = j.Data || {};
                  return {
                    Status: d.Status,
                    IndependentUrl: d.IndependentUrl,
                    FailedMessage: d.FailedMessage,
                  };
                }""",
                {"owner": OWNER, "name": NAME},
            )
            print("poll", i, st2.get("Status"))
            if st2.get("Status") in ("Running", "Failed", "Error"):
                final = st2
                break

        print("FINAL", json.dumps(final, ensure_ascii=False))
        put_ok = all(v.get("ok") for v in results.values())
        if not put_ok:
            return 3
        if final.get("Status") != "Running":
            return 4
        print("DEMO_URL", final.get("IndependentUrl") or f"https://{OWNER}-{NAME}.ms.show/")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
