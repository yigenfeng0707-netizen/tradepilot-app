const $ = (id) => document.getElementById(id);

let currentOrderId = null;

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

function money(cur, n) {
  const v = Number(n || 0);
  return `${cur || "USD"} ${v.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function renderResult(data) {
  $("results").classList.remove("hidden");
  const steps = [
    ["上传 / 入库", true],
    ["解析抽取", !!data.extraction],
    ["合同草稿", !!data.contract],
    ["PI / CI / PL", (data.generated_docs || []).length >= 3],
    ["一致性校验", !!data.consistency],
    ["P2 财务", !!data.order_id],
  ];
  const passed = data.consistency && data.consistency.passed;
  $("steps").innerHTML = steps
    .map(([label, ok], i) => {
      const last = i === steps.length - 1;
      const cls = last ? (ok ? "done" : "") : i === 4 ? (passed ? "done" : "fail") : ok ? "done" : "";
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

  if (data.order_id) {
    currentOrderId = data.order_id;
    $("p2").classList.remove("hidden");
    $("p2-order-no").textContent = data.order_no || `#${data.order_id}`;
    loadFinance(data.order_id);
  }
}

function settlementBadge(status) {
  const map = {
    matched: "badge ok",
    partial: "badge warn",
    unmatched: "badge muted",
    unknown: "badge muted",
  };
  return map[status] || "badge muted";
}

function renderFinance(bundle) {
  const s = bundle.settlement || {};
  const cur = s.currency || "USD";
  $("p2-settlement").innerHTML = `
    <div class="metric"><span>应收</span><strong>${money(cur, s.expected_amount)}</strong></div>
    <div class="metric"><span>已收</span><strong>${money(cur, s.received_amount)}</strong></div>
    <div class="metric"><span>待核销</span><strong>${money(cur, s.remaining_amount)}</strong></div>
    <div class="metric"><span>状态</span><strong class="${settlementBadge(s.status)}">${s.status_label || s.status || "—"}</strong></div>
  `;

  const pays = bundle.payments || [];
  $("p2-payments").innerHTML = pays.length
    ? `<table class="mini"><thead><tr><th>方向</th><th>金额</th><th>日期</th><th>匹配</th></tr></thead><tbody>
      ${pays
        .map(
          (p) => `<tr>
            <td>${p.direction === "in" ? "收入" : "支出"}</td>
            <td>${money(p.currency, p.amount)}</td>
            <td>${p.value_date || "—"}</td>
            <td>${p.matched ? "是" : "—"}</td>
          </tr>`
        )
        .join("")}
      </tbody></table>`
    : `<p class="hint">暂无收付记录。可点「写入演示收付+退税」或下方登记。</p>`;

  const rebates = bundle.rebates || [];
  $("p2-rebates").innerHTML = rebates.length
    ? `<table class="mini"><thead><tr><th>状态</th><th>申报金额</th><th>备注</th><th>操作</th></tr></thead><tbody>
      ${rebates
        .map((r) => {
          const st = r.status || "pending";
          const next =
            st === "pending"
              ? { status: "submitted", label: "提交申报" }
              : st === "submitted"
                ? { status: "received", label: "确认退税" }
                : null;
          const btn = next
            ? `<button type="button" class="linkish" data-rebate-id="${r.id}" data-next="${next.status}">${next.label}</button>`
            : `<span class="hint">已完成</span>`;
          return `<tr>
            <td><span class="badge ${st}">${r.status_label || st}</span></td>
            <td>${money(cur, r.claim_amount)}</td>
            <td>${r.notes || "—"}</td>
            <td>${btn}</td>
          </tr>`;
        })
        .join("")}
      </tbody></table>`
    : `<p class="hint">暂无退税台账。</p>`;

  $("p2-rebates").querySelectorAll("[data-rebate-id]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-rebate-id");
      const status = btn.getAttribute("data-next");
      try {
        const r = await fetch(`/api/finance/rebates/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status }),
        });
        const j = await r.json();
        if (!r.ok) throw new Error(j.detail || "更新失败");
        await loadFinance(currentOrderId);
      } catch (e) {
        showStatus(String(e.message || e), true);
      }
    });
  });

  const m = bundle.margin || {};
  $("p2-margin").innerHTML = `
    <div class="metric"><span>收入</span><strong>${money(m.currency, m.revenue)}</strong></div>
    <div class="metric"><span>成本(演示)</span><strong>${money(m.currency, m.cost)}</strong></div>
    <div class="metric"><span>毛利</span><strong>${money(m.currency, m.gross_profit)}</strong></div>
    <div class="metric"><span>毛利率</span><strong>${Number(m.margin_pct || 0).toFixed(1)}%</strong></div>
    <div class="metric"><span>退税估算</span><strong>${money(m.currency, m.rebate_estimate)}</strong></div>
  `;
}

async function loadFinance(orderId) {
  if (!orderId) return;
  try {
    const [bundleRes, marginRes] = await Promise.all([
      fetch(`/api/finance/orders/${orderId}`),
      fetch("/api/finance/margin?limit=8"),
    ]);
    const bundle = await bundleRes.json();
    if (!bundleRes.ok) throw new Error(bundle.detail || "财务加载失败");
    renderFinance(bundle);

    const margin = await marginRes.json();
    if (marginRes.ok) {
      const items = margin.items || [];
      $("p2-margin-table").innerHTML = items.length
        ? `<table class="mini"><thead><tr>
            <th>订单</th><th>收入</th><th>成本</th><th>毛利</th><th>毛利率</th><th>核销</th>
          </tr></thead><tbody>
          ${items
            .map(
              (i) => `<tr class="${i.order_id === orderId ? "hilite" : ""}">
                <td>${i.order_no || i.order_id}</td>
                <td>${money(i.currency, i.revenue)}</td>
                <td>${money(i.currency, i.cost)}</td>
                <td>${money(i.currency, i.gross_profit)}</td>
                <td>${Number(i.margin_pct || 0).toFixed(1)}%</td>
                <td>${i.settlement_label || "—"}</td>
              </tr>`
            )
            .join("")}
          </tbody></table>
          <p class="hint">合计毛利 ${money("USD", margin.summary?.gross_profit)} · ${margin.summary?.order_count || 0} 单</p>`
        : "";
    }
  } catch (e) {
    showStatus(String(e.message || e), true);
  }
}

async function seedFinance() {
  if (!currentOrderId) {
    showStatus("请先跑通 P1 订单", true);
    return;
  }
  try {
    const r = await fetch(`/api/finance/demo-seed/${currentOrderId}`, { method: "POST" });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || "写入失败");
    showStatus(
      `演示财务已写入 · 核销 ${j.settlement?.status_label || ""} · 退税 ${j.rebate?.status_label || ""}`
    );
    await loadFinance(currentOrderId);
  } catch (e) {
    showStatus(String(e.message || e), true);
  }
}

async function createRebate() {
  if (!currentOrderId) return;
  try {
    const r = await fetch("/api/finance/rebates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ order_id: currentOrderId, status: "pending" }),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || "创建失败");
    await loadFinance(currentOrderId);
  } catch (e) {
    showStatus(String(e.message || e), true);
  }
}

async function submitPayment(e) {
  e.preventDefault();
  if (!currentOrderId) {
    showStatus("请先跑通 P1 订单", true);
    return;
  }
  const amount = Number($("pay-amount").value);
  const direction = $("pay-direction").value;
  if (!(amount > 0)) {
    showStatus("请输入有效金额", true);
    return;
  }
  try {
    const r = await fetch("/api/finance/payments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        order_id: currentOrderId,
        amount,
        direction,
      }),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || "登记失败");
    $("pay-amount").value = "";
    showStatus(`收付已登记 · ${j.settlement?.status_label || ""}`);
    await loadFinance(currentOrderId);
  } catch (err) {
    showStatus(String(err.message || err), true);
  }
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
$("btn-finance-seed").addEventListener("click", seedFinance);
$("btn-finance-refresh").addEventListener("click", () => loadFinance(currentOrderId));
$("btn-rebate-create").addEventListener("click", createRebate);
$("pay-form").addEventListener("submit", submitPayment);

refreshHealth();
