"""PO / document field extraction — rules first, optional LLM-2."""
from __future__ import annotations

import re
from typing import Any

from .llm import LLMClient


def _confidence(level: str) -> str:
    return level  # high | medium | low


def extract_po_rules(text: str) -> dict[str, Any]:
    """Deterministic extractor aligned with Appendix C sample fields."""
    fields: dict[str, Any] = {
        "buyer": None,
        "seller": None,
        "po_no": None,
        "product_name": None,
        "qty": None,
        "unit": "PCS",
        "unit_price": None,
        "currency": "USD",
        "total_amount": None,
        "trade_term": None,
        "destination": None,
        "payment_terms": "30% T/T in advance, 70% against B/L copy",
        "packages": None,
    }
    conf: dict[str, str] = {}

    m = re.search(r"(?:PO|Purchase\s*Order)\s*No\.?\s*[:：]?\s*([A-Z0-9\-_/]+)", text, re.I)
    if m:
        fields["po_no"] = m.group(1).strip()
        conf["po_no"] = _confidence("high")

    m = re.search(r"(?:Buyer|买方|Purchaser)\s*[:：]\s*(.+)", text, re.I)
    if m:
        fields["buyer"] = m.group(1).strip().split("\n")[0].strip()
        conf["buyer"] = _confidence("high")

    m = re.search(r"(?:Seller|卖方|Supplier)\s*[:：]\s*(.+)", text, re.I)
    if m:
        fields["seller"] = m.group(1).strip().split("\n")[0].strip()
        conf["seller"] = _confidence("high")

    m = re.search(
        r"(?:Item|品名|Description)\s*[:：]\s*(.+?)(?:\n|$)",
        text,
        re.I,
    )
    if m:
        fields["product_name"] = m.group(1).strip()
        conf["product_name"] = _confidence("high")
    else:
        m = re.search(r"(LED\s+Panel\s+Light[^\n,]*)", text, re.I)
        if m:
            fields["product_name"] = m.group(1).strip()
            conf["product_name"] = _confidence("high")

    m = re.search(r"(?:Qty|Quantity|数量)\s*[:：]?\s*([\d,]+)\s*(PCS|pcs|件)?", text, re.I)
    if m:
        fields["qty"] = float(m.group(1).replace(",", ""))
        if m.group(2):
            fields["unit"] = m.group(2).upper().replace("件", "PCS")
        conf["qty"] = _confidence("high")

    m = re.search(
        r"(?:Unit\s*Price|单价)\s*[:：]?\s*(?:USD|US\$|\$)?\s*([\d,.]+)",
        text,
        re.I,
    )
    if m:
        fields["unit_price"] = float(m.group(1).replace(",", ""))
        conf["unit_price"] = _confidence("high")

    m = re.search(
        r"(?:Total|Amount|总额|总价)\s*[:：]?\s*(?:USD|US\$|\$)?\s*([\d,.]+)",
        text,
        re.I,
    )
    if m:
        fields["total_amount"] = float(m.group(1).replace(",", ""))
        conf["total_amount"] = _confidence("medium")

    m = re.search(r"\b(CIF|FOB|CFR|EXW|DDP)\s+([A-Za-z ]+)", text, re.I)
    if m:
        fields["trade_term"] = m.group(1).upper()
        fields["destination"] = m.group(2).strip()
        conf["trade_term"] = _confidence("high")
        conf["destination"] = _confidence("high")
    else:
        m = re.search(r"(?:Trade\s*Term|贸易术语)\s*[:：]\s*(.+)", text, re.I)
        if m:
            raw = m.group(1).strip()
            fields["trade_term"] = raw
            conf["trade_term"] = _confidence("high")

    m = re.search(r"(?:Payment|付款)\s*[:：]\s*(.+)", text, re.I)
    if m:
        fields["payment_terms"] = m.group(1).strip().split("\n")[0].strip()
        conf["payment_terms"] = _confidence("high")

    # 金额交叉校验
    if fields["qty"] and fields["unit_price"]:
        calc = round(fields["qty"] * fields["unit_price"], 2)
        if fields["total_amount"] is None:
            fields["total_amount"] = calc
            conf["total_amount"] = _confidence("high")
        elif abs(fields["total_amount"] - calc) < 0.05:
            conf["total_amount"] = _confidence("high")
            conf["unit_price"] = _confidence("high")
        else:
            conf["total_amount"] = _confidence("medium")
            conf["unit_price"] = _confidence("medium")
            fields["_amount_mismatch"] = {
                "stated": fields["total_amount"],
                "calculated": calc,
            }

    if fields["packages"] is None and fields["qty"]:
        # 演示默认：每箱 50 PCS
        fields["packages"] = int(fields["qty"] // 50) or 1

    return {"fields": fields, "confidence": conf, "extractor": "rules"}


def extract_po(text: str, llm: LLMClient | None = None) -> dict[str, Any]:
    base = extract_po_rules(text)
    llm = llm or LLMClient()
    fallback = {
        "fields": base["fields"],
        "confidence": base["confidence"],
        "notes": "rules fallback",
    }
    enriched, meta = llm.chat_json(
        call_point="LLM-2",
        system=(
            "You extract structured fields from a foreign-trade Purchase Order. "
            "Return JSON with keys: fields, confidence, notes. "
            "Keep numeric types as numbers. Do not invent buyer names if absent."
        ),
        user=f"PO text:\n{text[:6000]}\n\nSeed extraction:\n{base}",
        fallback=fallback,
    )
    fields = {**base["fields"], **(enriched.get("fields") or {})}
    conf = {**base["confidence"], **(enriched.get("confidence") or {})}
    # 再次强制金额守恒
    if fields.get("qty") and fields.get("unit_price"):
        calc = round(float(fields["qty"]) * float(fields["unit_price"]), 2)
        stated = fields.get("total_amount")
        if stated is None or abs(float(stated) - calc) < 0.05:
            fields["total_amount"] = calc
            conf["total_amount"] = "high"
        else:
            conf["total_amount"] = "medium"
            fields["_amount_mismatch"] = {"stated": float(stated), "calculated": calc}

    source = meta.get("model") or meta.get("fallback_used") or "rules"
    return {
        "fields": fields,
        "confidence": conf,
        "extractor": f"llm:{source}" if meta.get("mode") == "api" and meta.get("success") else f"rules+{source}",
        "llm_meta": meta,
        "notes": enriched.get("notes"),
    }
