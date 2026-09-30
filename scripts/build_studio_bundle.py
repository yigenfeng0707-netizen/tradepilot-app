"""Build single-file index.html for Docker Studio (only existing path can PUT)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "deploy-studio"
css = (ROOT / "styles.css").read_text(encoding="utf-8")
sample = (ROOT / "sample-result.json").read_text(encoding="utf-8")

js = r"""
const $ = (id) => document.getElementById(id);
function showStatus(msg, err = false) {
  const el = $("status");
  el.classList.remove("hidden");
  el.classList.toggle("err", err);
  el.textContent = msg;
}
function renderResult(data) {
  $("results").classList.remove("hidden");
  const steps = [
    ["上传 / 入库", true],
    ["解析抽取", !!data.extraction],
    ["合同草稿", !!data.contract],
    ["PI / CI / PL", (data.generated_docs || []).length >= 3],
    ["一致性校验", !!data.consistency],
  ];
  const passed = data.consistency && data.consistency.passed;
  $("steps").innerHTML = steps
    .map(([label, ok], i) => {
      const last = i === steps.length - 1;
      const cls = last ? (passed ? "done" : "fail") : ok ? "done" : "";
      return `<li class="${cls}">${label}</li>`;
    })
    .join("");
  const c = $("consistency");
  c.className = "consistency " + (passed ? "pass" : "fail");
  c.textContent = data.consistency ? data.consistency.summary : "无校验结果";
  $("extract").textContent = JSON.stringify(
    {
      extractor: data.extraction?.extractor,
      fields: data.extraction?.fields,
      confidence: data.extraction?.confidence,
    },
    null,
    2
  );
  $("contract").textContent = data.contract?.preview || "";
  $("docs").innerHTML = (data.generated_docs || [])
    .map(
      (d) =>
        `<div class="doc-row"><strong>${d.doc_type.toUpperCase()}</strong>
        <span class="file-link">本地完整版可下载 PDF</span>
        <code>${d.path || ""}</code></div>
        <pre>${(d.preview || "").slice(0, 800)}</pre>`
    )
    .join("");
  $("audit").textContent = JSON.stringify(data.audit_tail || [], null, 2);
}
async function runSample() {
  $("btn-sample").disabled = true;
  showStatus("正在加载魔搭样例回放…");
  try {
    const j = window.__SAMPLE__;
    showStatus(
      `回放完成 · 订单 ${j.order_no} · 抽取=${(j.extraction && j.extraction.extractor) || ""}`
    );
    renderResult(j);
  } catch (e) {
    showStatus(String(e.message || e), true);
  } finally {
    $("btn-sample").disabled = false;
  }
}
$("btn-sample").addEventListener("click", runSample);
"""

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>TradePilot · P1 Demo</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,600;0,9..40,700;1,9..40,400&family=Source+Serif+4:opsz,wght@8..60,600;8..60,700&display=swap" rel="stylesheet" />
  <style>
{css}
  </style>
</head>
<body>
  <div class="bg-grid" aria-hidden="true"></div>
  <header class="top">
    <div class="brand">
      <span class="mark">TP</span>
      <div>
        <div class="name">TradePilot</div>
        <div class="tag">外贸全链路 AI 数字员工 · 创空间演示</div>
      </div>
    </div>
    <div id="health" class="pill ok">魔搭演示 · 样例回放</div>
  </header>
  <main>
    <section class="hero-panel">
      <h1>上传 PO → 合同草稿 → PI / CI / PL</h1>
      <p class="lede">一源多单演示：回放已用魔搭开源 Qwen 跑通的样例结果。完整 OCR / 真 API / PDF 出单见本地 tradepilot-app。</p>
      <div class="actions">
        <button type="button" id="btn-sample" class="primary">回放样例全链路</button>
      </div>
    </section>
    <section id="status" class="status hidden" aria-live="polite"></section>
    <section id="results" class="results hidden">
      <div class="rail">
        <h2>流水线</h2>
        <ol id="steps" class="steps"></ol>
        <div id="consistency" class="consistency"></div>
      </div>
      <div class="panels">
        <article><h3>抽取字段</h3><pre id="extract"></pre></article>
        <article><h3>合同草稿预览</h3><pre id="contract"></pre></article>
        <article><h3>交付物</h3><div id="docs" class="docs"></div></article>
        <article><h3>审计链（最近）</h3><pre id="audit"></pre></article>
      </div>
    </section>
  </main>
  <footer><span>评分码参考 T02-W-0081 · 魔搭开源模型实测</span></footer>
  <script>window.__SAMPLE__ = {sample};</script>
  <script>
{js}
  </script>
</body>
</html>
"""

out = ROOT / "index.html"
out.write_text(html, encoding="utf-8")
print("wrote", out, "bytes", out.stat().st_size)
