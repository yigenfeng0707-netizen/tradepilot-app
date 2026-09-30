#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P2 finance smoke: payment settlement + rebate ledger + margin. Prints P2_OK."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import finance as finance_svc  # noqa: E402
from app.services.pipeline import load_sample_po, run_pipeline  # noqa: E402


def main() -> int:
    text, name = load_sample_po()
    result = run_pipeline(raw_text=text, original_filename=name)
    order_id = int(result["order_id"])
    expected = float(result["extraction"]["fields"].get("total_amount") or 16000)

    seed = finance_svc.seed_demo_finance(order_id)
    settlement = finance_svc.get_settlement(order_id)
    # 补尾款至全额核销
    remaining = float(settlement.get("remaining_amount") or 0)
    if remaining > 0.01:
        finance_svc.create_payment(order_id=order_id, amount=remaining, direction="in")
        settlement = finance_svc.get_settlement(order_id)

    rebates = finance_svc.list_rebates(order_id=order_id)
    if not rebates:
        finance_svc.create_rebate(order_id=order_id, status="pending")
        rebates = finance_svc.list_rebates(order_id=order_id)
    rid = int(rebates[0]["id"])
    finance_svc.update_rebate(rid, status="submitted")
    finance_svc.update_rebate(rid, status="received")
    rebates = finance_svc.list_rebates(order_id=order_id)

    margin = finance_svc.margin_report(order_id=order_id)
    item = (margin.get("items") or [{}])[0]
    bundle = finance_svc.finance_bundle(order_id)

    checks = [
        ("pipeline_ok", bool(result.get("ok"))),
        ("seed_partial_or_matched", seed["settlement"]["status"] in {"partial", "matched"}),
        ("settlement_matched", settlement.get("status") == "matched"),
        ("received_ge_expected", float(settlement.get("received_amount") or 0) + 0.01 >= expected),
        ("rebate_received", rebates and rebates[0].get("status") == "received"),
        ("rebate_label", rebates and rebates[0].get("status_label") == "已退税"),
        ("margin_revenue", abs(float(item.get("revenue") or 0) - expected) < 0.05),
        ("margin_positive", float(item.get("gross_profit") or 0) > 0),
        ("bundle_ok", bundle.get("order_id") == order_id),
    ]
    failed = [name for name, ok in checks if not ok]
    summary = {
        "order_id": order_id,
        "order_no": result.get("order_no"),
        "settlement": settlement.get("status_label"),
        "rebate": rebates[0].get("status_label") if rebates else None,
        "margin_pct": item.get("margin_pct"),
        "failed": failed,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if failed:
        print("P2_SMOKE_FAILED")
        return 1
    print("P2_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
