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
    .map(
      (d) => `<div class="doc-row"><strong>${d.doc_type.toUpperCase()}</strong>
        <span class="file-link">本地可下载 PDF</span>
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
    const r = await fetch("./sample-result.json");
    const j = await r.json();
    showStatus(`回放完成 · 订单 ${j.order_no} · 抽取=${j.extraction?.extractor || ""}`);
    renderResult(j);
  } catch (e) {
    showStatus(String(e.message || e), true);
  } finally {
    $("btn-sample").disabled = false;
  }
}

$("btn-sample").addEventListener("click", runSample);
