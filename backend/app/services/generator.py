"""Contract + PI/CI/PL generation from single order source."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import get_settings
from .llm import LLMClient

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(enabled_extensions=("html",)),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def build_context(order: dict[str, Any], line: dict[str, Any], extras: dict[str, Any] | None = None) -> dict[str, Any]:
    qty = float(line["qty"])
    packages = int(line.get("packages") or max(1, int(qty // 50)))
    gw = float(line.get("gross_weight_kg") or packages * 12.5)
    nw = float(line.get("net_weight_kg") or packages * 11.0)
    cbm = float(line.get("volume_cbm") or round(packages * 0.08, 3))
    ctx = {
        "order": order,
        "line": line,
        "packages": packages,
        "gross_weight_kg": gw,
        "net_weight_kg": nw,
        "volume_cbm": cbm,
        "bank": extras.get("bank") if extras else None,
        "buyer": extras.get("buyer") if extras else None,
        "seller": extras.get("seller") if extras else None,
        "risk_alerts": extras.get("risk_alerts") if extras else [],
        "hs_code": line.get("hs_code") or "9405110000",
        "declare_elements": extras.get("declare_elements") or "品牌;型号;功率;尺寸",
    }
    return ctx


def detect_risks(order: dict[str, Any], settings=None) -> list[str]:
    settings = settings or get_settings()
    alerts: list[str] = []
    payment = (order.get("payment_terms") or "").lower()
    import re

    m = re.search(r"(\d+)\s*%", payment)
    if m:
        ratio = int(m.group(1)) / 100.0
        if ratio >= settings.prepaid_risk_threshold:
            alerts.append(
                f"预付比例 {ratio:.0%} ≥ 风险阈值 {settings.prepaid_risk_threshold:.0%}，建议人工复核资金风险。"
            )
    if not order.get("trade_term"):
        alerts.append("贸易术语缺失，合同关键条款无法自动填充运保责任。")
    return alerts


def render_contract(ctx: dict[str, Any], llm: LLMClient | None = None) -> dict[str, Any]:
    env = _env()
    body = env.get_template("contract_zh_en.md.j2").render(**ctx)
    llm = llm or LLMClient()
    fallback = {"body_md": body, "polish_notes": "template only"}
    polished, meta = llm.chat_json(
        call_point="LLM-3",
        system="You polish a bilingual sales contract draft. Return JSON: {body_md, polish_notes}. Keep all numbers unchanged.",
        user=body[:8000],
        fallback=fallback,
    )
    out_body = polished.get("body_md") or body
    # 数字守恒：禁止 LLM 改总额
    total = ctx["order"].get("total_amount")
    if total is not None and f"{total:,.2f}" not in out_body.replace(",", "") and f"{total:.2f}" not in out_body:
        out_body = body
        meta["fallback_used"] = meta.get("fallback_used") or "template_number_guard"
    source = meta.get("model") or meta.get("fallback_used") or "template"
    return {
        "body_md": out_body,
        "generator": f"jinja2+{source}",
        "llm_meta": meta,
        "polish_notes": polished.get("polish_notes"),
    }


def render_docs(ctx: dict[str, Any]) -> dict[str, dict[str, Any]]:
    env = _env()
    order = ctx["order"]
    line = ctx["line"]
    base_fields = {
        "currency": order.get("currency") or "USD",
        "trade_term": order.get("trade_term"),
        "destination": order.get("destination"),
        "product_name": line.get("product_name"),
        "qty": line.get("qty"),
        "unit": line.get("unit") or "PCS",
        "unit_price": line.get("unit_price"),
        "total_amount": order.get("total_amount"),
        "packages": ctx["packages"],
        "gross_weight_kg": ctx["gross_weight_kg"],
        "net_weight_kg": ctx["net_weight_kg"],
        "volume_cbm": ctx["volume_cbm"],
        "hs_code": ctx["hs_code"],
    }
    docs = {}
    for key, tpl, dtype in [
        ("pi", "pi.md.j2", "pi"),
        ("ci", "ci.md.j2", "ci"),
        ("pl", "pl.md.j2", "pl"),
        ("customs", "customs_elements.md.j2", "customs_elements"),
    ]:
        text = env.get_template(tpl).render(**ctx)
        docs[key] = {
            "doc_type": dtype,
            "body_md": text,
            "fields": dict(base_fields),
        }
    return docs


def consistency_check(order: dict[str, Any], line: dict[str, Any], docs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    diffs: list[dict[str, Any]] = []
    expected_amount = float(order["total_amount"])
    expected_qty = float(line["qty"])
    expected_term = order.get("trade_term")

    for name, doc in docs.items():
        if name == "customs":
            continue
        fields = doc["fields"]
        if abs(float(fields.get("total_amount") or 0) - expected_amount) > 0.01:
            diffs.append(
                {
                    "field": "total_amount",
                    "source_a": "contract/order",
                    "source_b": name.upper(),
                    "expected": expected_amount,
                    "actual": fields.get("total_amount"),
                }
            )
        if abs(float(fields.get("qty") or 0) - expected_qty) > 0.01:
            diffs.append(
                {
                    "field": "qty",
                    "source_a": "PO/order",
                    "source_b": name.upper(),
                    "expected": expected_qty,
                    "actual": fields.get("qty"),
                }
            )
        if expected_term and fields.get("trade_term") != expected_term:
            diffs.append(
                {
                    "field": "trade_term",
                    "source_a": "contract/order",
                    "source_b": name.upper(),
                    "expected": expected_term,
                    "actual": fields.get("trade_term"),
                }
            )

    calc = round(float(line["unit_price"]) * float(line["qty"]), 2)
    if abs(calc - expected_amount) > 0.01:
        diffs.append(
            {
                "field": "amount_equation",
                "source_a": "unit_price*qty",
                "source_b": "order.total_amount",
                "expected": calc,
                "actual": expected_amount,
            }
        )

    passed = len(diffs) == 0
    return {
        "passed": passed,
        "summary": "一致性校验通过" if passed else f"发现 {len(diffs)} 处冲突，已阻断流转",
        "diffs": diffs,
    }


def write_output(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)
