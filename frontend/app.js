const $ = (id) => document.getElementById(id);

async function refreshHealth() {
  const el = $("health");
  try {
    const r = await fetch("/api/health");
    const j = await r.json();
    const provider = j.llm_provider || j.llm_mode || "mock";
    const model = j.llm_model || "";
    const shortModel = model.includes("/") ? model.split("/").pop() : model;
    if (j.real_llm_ready) {
      el.textContent = `魔搭 · ${shortModel || provider}`;
      el.title = j.message || model;
      el.className = "pill ok";
    } else if (j.demo_ready) {
      el.textContent = "就绪 · 规则引擎";
      el.title = j.message || "";
      el.className = "pill ok";
    } else {
      el.textContent = "可启动 · LLM 未配置";
      el.className = "pill warn";
    }
  } catch {
    el.textContent = "后端未连接";
    el.className = "pill warn";
  }
}

function setBusy(busy) {
  $("btn-sample").disabled = busy;
  const imgBtn = $("btn-sample-img");
  if (imgBtn) imgBtn.disabled = busy;
  $("btn-paste").disabled = busy;
}

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
  c.textContent = data.consistency
    ? data.consistency.summary
    : "无校验结果";

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
    .map((d) => {
      const pdf = d.pdf_path
        ? `<a class="file-link" href="/api/files?path=${encodeURIComponent(d.pdf_path)}" target="_blank" rel="noopener">PDF</a>`
        : "";
      const md = d.path
        ? `<a class="file-link" href="/api/files?path=${encodeURIComponent(d.path)}" target="_blank" rel="noopener">MD</a>`
        : "";
      return `<div class="doc-row"><strong>${d.doc_type.toUpperCase()}</strong> ${pdf} ${md}
        <code>${d.path || ""}</code></div>
        <pre>${(d.preview || "").slice(0, 800)}</pre>`;
    })
    .join("");
  document.querySelectorAll(".file-row").forEach((n) => n.remove());
  const contractPdf = data.contract?.pdf_path;
  if (contractPdf) {
    $("contract").insertAdjacentHTML(
      "beforebegin",
      `<p class="file-row"><a class="file-link" href="/api/files?path=${encodeURIComponent(contractPdf)}" target="_blank" rel="noopener">下载合同 PDF</a></p>`
    );
  }
  $("audit").textContent = JSON.stringify(data.audit_tail || [], null, 2);
}

async function runSample() {
  setBusy(true);
  showStatus("正在跑通样例 PO-2026-0913…");
  try {
    const r = await fetch("/api/orders/sample", { method: "POST" });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || "失败");
    showStatus(
      `完成 · 订单 ${j.order_no} · 校验${j.ok ? "通过" : "未通过"} · LLM=${j.llm_mode}`
    );
    renderResult(j);
  } catch (e) {
    showStatus(String(e.message || e), true);
  } finally {
    setBusy(false);
  }
}

async function runSampleImage() {
  setBusy(true);
  showStatus("正在 OCR 样例扫描件并用魔搭模型抽取…");
  try {
    const r = await fetch("/api/orders/sample-image", { method: "POST" });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || "失败");
    const kind = j.read_meta?.source_kind || "image_ocr";
    showStatus(
      `完成 · 订单 ${j.order_no} · ${kind} · 校验${j.ok ? "通过" : "未通过"}`
    );
    renderResult(j);
  } catch (e) {
    showStatus(String(e.message || e), true);
  } finally {
    setBusy(false);
  }
}

async function runText() {
  const text = $("paste").value.trim();
  if (text.length < 20) {
    showStatus("请粘贴更完整的 PO 文本", true);
    return;
  }
  setBusy(true);
  showStatus("正在解析粘贴文本…");
  try {
    const r = await fetch("/api/orders/pipeline/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, filename: "pasted-po.txt" }),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || "失败");
    showStatus(`完成 · 订单 ${j.order_no}`);
    renderResult(j);
  } catch (e) {
    showStatus(String(e.message || e), true);
  } finally {
    setBusy(false);
  }
}

async function runFile(file) {
  setBusy(true);
  showStatus(`正在上传 ${file.name}…`);
  try {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch("/api/orders/pipeline", { method: "POST", body: fd });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || "失败");
    showStatus(`完成 · 订单 ${j.order_no}`);
    renderResult(j);
  } catch (e) {
    showStatus(String(e.message || e), true);
  } finally {
    setBusy(false);
  }
}

$("btn-sample").addEventListener("click", runSample);
if ($("btn-sample-img")) {
  $("btn-sample-img").addEventListener("click", runSampleImage);
}
$("btn-paste").addEventListener("click", runText);
$("file").addEventListener("change", (e) => {
  const f = e.target.files && e.target.files[0];
  if (f) runFile(f);
});

refreshHealth();
