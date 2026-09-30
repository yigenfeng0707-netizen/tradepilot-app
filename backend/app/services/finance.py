"""P2 finance MVP: 收付汇核销 · 退税三态台账 · 订单毛利报表."""
from __future__ import annotations

from datetime import date
from typing import Any

from app.db import execute, fetchall, fetchone, get_conn
from app.services.pipeline import ensure_db

TENANT_ID = 1

# 演示成本率：无采购成本字段时，按收入 × 比例估算成本
DEMO_COST_RATIO = 0.72

# 退税三态（UI 中文）
REBATE_STATES = {
    "pending": "待申报",
    "submitted": "已申报",
    "received": "已退税",
}
REBATE_ALIASES = {
    "draft": "pending",
    "待申报": "pending",
    "eligible": "pending",
    "submitted": "submitted",
    "已申报": "submitted",
    "claimed": "submitted",
    "received": "received",
    "已退税": "received",
    "rejected": "pending",
}


def _normalize_rebate_status(raw: str | None) -> str:
    key = (raw or "pending").strip().lower()
    # keep Chinese keys as-is for alias map
    if raw and raw.strip() in REBATE_ALIASES:
        return REBATE_ALIASES[raw.strip()]
    return REBATE_ALIASES.get(key, key if key in REBATE_STATES else "pending")


def _label_rebate(status: str) -> str:
    return REBATE_STATES.get(_normalize_rebate_status(status), status)


def _get_order(conn, order_id: int) -> dict[str, Any] | None:
    return fetchone(conn, "SELECT * FROM trade_orders WHERE id=?", (order_id,))


def _order_expected_amount(order: dict[str, Any]) -> float:
    return float(order.get("total_amount") or 0)


def _sum_payments(conn, order_id: int, direction: str | None = None) -> float:
    if direction:
        row = fetchone(
            conn,
            "SELECT COALESCE(SUM(amount),0) AS s FROM payment_records "
            "WHERE order_id=? AND direction=?",
            (order_id, direction),
        )
    else:
        row = fetchone(
            conn,
            "SELECT COALESCE(SUM(CASE WHEN direction='in' THEN amount "
            "WHEN direction='out' THEN -amount ELSE 0 END),0) AS s "
            "FROM payment_records WHERE order_id=?",
            (order_id,),
        )
    return float((row or {}).get("s") or 0)


def settlement_for_order(conn, order: dict[str, Any]) -> dict[str, Any]:
    order_id = int(order["id"])
    expected = _order_expected_amount(order)
    received = _sum_payments(conn, order_id, "in")
    paid_out = _sum_payments(conn, order_id, "out")
    remaining = round(expected - received, 2)
    if expected <= 0:
        status = "unknown"
        status_label = "无金额"
    elif received <= 0.01:
        status = "unmatched"
        status_label = "未核销"
    elif remaining > 0.01:
        status = "partial"
        status_label = "部分核销"
    else:
        status = "matched"
        status_label = "已核销"
        remaining = 0.0
    ratio = (received / expected) if expected else 0.0
    return {
        "order_id": order_id,
        "order_no": order.get("order_no"),
        "currency": order.get("currency") or "USD",
        "expected_amount": expected,
        "received_amount": round(received, 2),
        "paid_out_amount": round(paid_out, 2),
        "remaining_amount": remaining,
        "settlement_ratio": round(ratio, 4),
        "status": status,
        "status_label": status_label,
    }


def list_payments(order_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    ensure_db()
    with get_conn() as conn:
        if order_id is not None:
            rows = fetchall(
                conn,
                "SELECT p.*, o.order_no FROM payment_records p "
                "LEFT JOIN trade_orders o ON o.id=p.order_id "
                "WHERE p.order_id=? ORDER BY p.id DESC LIMIT ?",
                (order_id, limit),
            )
        else:
            rows = fetchall(
                conn,
                "SELECT p.*, o.order_no FROM payment_records p "
                "LEFT JOIN trade_orders o ON o.id=p.order_id "
                "ORDER BY p.id DESC LIMIT ?",
                (limit,),
            )
    return rows


def create_payment(
    *,
    order_id: int,
    amount: float,
    direction: str = "in",
    currency: str | None = None,
    value_date: str | None = None,
    fx_rate: float | None = None,
    auto_match: bool = True,
) -> dict[str, Any]:
    ensure_db()
    direction = (direction or "in").lower()
    if direction not in {"in", "out"}:
        raise ValueError("direction 须为 in 或 out")
    if amount <= 0:
        raise ValueError("amount 须为正数")
    with get_conn() as conn:
        order = _get_order(conn, order_id)
        if not order:
            raise LookupError("订单不存在")
        cur = currency or order.get("currency") or "USD"
        vd = value_date or date.today().isoformat()
        pid = execute(
            conn,
            """
            INSERT INTO payment_records
              (tenant_id, order_id, direction, amount, currency, value_date, matched, fx_rate)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (TENANT_ID, order_id, direction, float(amount), cur, vd, fx_rate),
        )
        settlement = settlement_for_order(conn, order)
        matched = 1 if settlement["status"] == "matched" and direction == "in" else 0
        if auto_match:
            # 标记本笔是否贡献了全额核销；部分核销时 matched=0
            if direction == "in" and settlement["status"] in {"matched", "partial"}:
                matched = 1 if settlement["status"] == "matched" else 0
            execute(conn, "UPDATE payment_records SET matched=? WHERE id=?", (matched, pid))
        row = fetchone(conn, "SELECT * FROM payment_records WHERE id=?", (pid,))
    return {"payment": row, "settlement": settlement}


def get_settlement(order_id: int) -> dict[str, Any]:
    ensure_db()
    with get_conn() as conn:
        order = _get_order(conn, order_id)
        if not order:
            raise LookupError("订单不存在")
        settlement = settlement_for_order(conn, order)
        payments = fetchall(
            conn,
            "SELECT * FROM payment_records WHERE order_id=? ORDER BY id",
            (order_id,),
        )
    settlement["payments"] = payments
    return settlement


def list_rebates(order_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    ensure_db()
    with get_conn() as conn:
        if order_id is not None:
            rows = fetchall(
                conn,
                "SELECT r.*, o.order_no FROM tax_rebate_claims r "
                "LEFT JOIN trade_orders o ON o.id=r.order_id "
                "WHERE r.order_id=? ORDER BY r.id DESC LIMIT ?",
                (order_id, limit),
            )
        else:
            rows = fetchall(
                conn,
                "SELECT r.*, o.order_no FROM tax_rebate_claims r "
                "LEFT JOIN trade_orders o ON o.id=r.order_id "
                "ORDER BY r.id DESC LIMIT ?",
                (limit,),
            )
    for r in rows:
        st = _normalize_rebate_status(r.get("status"))
        r["status"] = st
        r["status_label"] = _label_rebate(st)
    return rows


def create_rebate(
    *,
    order_id: int,
    claim_amount: float | None = None,
    status: str = "pending",
    notes: str | None = None,
) -> dict[str, Any]:
    ensure_db()
    st = _normalize_rebate_status(status)
    with get_conn() as conn:
        order = _get_order(conn, order_id)
        if not order:
            raise LookupError("订单不存在")
        if claim_amount is None:
            claim_amount = _estimate_rebate_amount(conn, order)
        rid = execute(
            conn,
            """
            INSERT INTO tax_rebate_claims
              (tenant_id, order_id, status, claim_amount, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (TENANT_ID, order_id, st, float(claim_amount), notes),
        )
        row = fetchone(conn, "SELECT * FROM tax_rebate_claims WHERE id=?", (rid,))
    assert row is not None
    row["status"] = st
    row["status_label"] = _label_rebate(st)
    return row


def update_rebate(
    rebate_id: int,
    *,
    status: str | None = None,
    claim_amount: float | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    ensure_db()
    with get_conn() as conn:
        row = fetchone(conn, "SELECT * FROM tax_rebate_claims WHERE id=?", (rebate_id,))
        if not row:
            raise LookupError("退税记录不存在")
        new_status = _normalize_rebate_status(status) if status is not None else row["status"]
        new_status = _normalize_rebate_status(new_status)
        new_amount = float(claim_amount) if claim_amount is not None else row.get("claim_amount")
        new_notes = notes if notes is not None else row.get("notes")
        execute(
            conn,
            "UPDATE tax_rebate_claims SET status=?, claim_amount=?, notes=? WHERE id=?",
            (new_status, new_amount, new_notes, rebate_id),
        )
        row = fetchone(conn, "SELECT * FROM tax_rebate_claims WHERE id=?", (rebate_id,))
    assert row is not None
    row["status"] = new_status
    row["status_label"] = _label_rebate(new_status)
    return row


def _estimate_rebate_amount(conn, order: dict[str, Any]) -> float:
    """按行项目 HS 退税率估算；缺省 13%。"""
    lines = fetchall(conn, "SELECT * FROM order_line_items WHERE order_id=?", (order["id"],))
    total = 0.0
    for line in lines:
        rate = 0.13
        hs = line.get("hs_code")
        if hs:
            hs_row = fetchone(conn, "SELECT rebate_rate FROM hs_codes WHERE code=?", (hs,))
            if hs_row and hs_row.get("rebate_rate") is not None:
                rate = float(hs_row["rebate_rate"])
        amt = float(line.get("amount") or 0)
        total += amt * rate
    if total <= 0 and order.get("total_amount"):
        total = float(order["total_amount"]) * 0.13
    return round(total, 2)


def _rebate_rate_for_order(conn, order: dict[str, Any]) -> float:
    lines = fetchall(conn, "SELECT * FROM order_line_items WHERE order_id=?", (order["id"],))
    for line in lines:
        hs = line.get("hs_code")
        if hs:
            hs_row = fetchone(conn, "SELECT rebate_rate FROM hs_codes WHERE code=?", (hs,))
            if hs_row and hs_row.get("rebate_rate") is not None:
                return float(hs_row["rebate_rate"])
    return 0.13


def margin_for_order(conn, order: dict[str, Any]) -> dict[str, Any]:
    order_id = int(order["id"])
    lines = fetchall(conn, "SELECT * FROM order_line_items WHERE order_id=?", (order_id,))
    revenue = float(order.get("total_amount") or 0)
    if not revenue and lines:
        revenue = sum(float(l.get("amount") or 0) for l in lines)
    # 演示成本：行金额 × DEMO_COST_RATIO（无真实采购价）
    cost = round(revenue * DEMO_COST_RATIO, 2)
    gross = round(revenue - cost, 2)
    margin_pct = round((gross / revenue) * 100, 2) if revenue else 0.0
    rebate_rate = _rebate_rate_for_order(conn, order)
    rebate_est = round(revenue * rebate_rate, 2)
    settlement = settlement_for_order(conn, order)
    rebate_rows = fetchall(
        conn,
        "SELECT * FROM tax_rebate_claims WHERE order_id=? ORDER BY id DESC",
        (order_id,),
    )
    rebate_claimed = sum(float(r.get("claim_amount") or 0) for r in rebate_rows if r.get("status") == "received")
    rebate_pipeline = sum(
        float(r.get("claim_amount") or 0)
        for r in rebate_rows
        if _normalize_rebate_status(r.get("status")) in {"pending", "submitted"}
    )
    return {
        "order_id": order_id,
        "order_no": order.get("order_no"),
        "po_no": order.get("po_no"),
        "currency": order.get("currency") or "USD",
        "revenue": round(revenue, 2),
        "cost": cost,
        "cost_basis": f"demo_ratio_{DEMO_COST_RATIO}",
        "gross_profit": gross,
        "margin_pct": margin_pct,
        "rebate_rate": rebate_rate,
        "rebate_estimate": rebate_est,
        "rebate_received": round(rebate_claimed, 2),
        "rebate_in_pipeline": round(rebate_pipeline, 2),
        "settlement_status": settlement["status"],
        "settlement_label": settlement["status_label"],
        "line_count": len(lines),
        "created_at": order.get("created_at"),
    }


def margin_report(order_id: int | None = None, limit: int = 30) -> dict[str, Any]:
    ensure_db()
    with get_conn() as conn:
        if order_id is not None:
            order = _get_order(conn, order_id)
            if not order:
                raise LookupError("订单不存在")
            items = [margin_for_order(conn, order)]
        else:
            orders = fetchall(
                conn,
                "SELECT * FROM trade_orders ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            items = [margin_for_order(conn, o) for o in orders]
    total_rev = sum(i["revenue"] for i in items)
    total_cost = sum(i["cost"] for i in items)
    total_gp = sum(i["gross_profit"] for i in items)
    return {
        "items": items,
        "summary": {
            "order_count": len(items),
            "revenue": round(total_rev, 2),
            "cost": round(total_cost, 2),
            "gross_profit": round(total_gp, 2),
            "margin_pct": round((total_gp / total_rev) * 100, 2) if total_rev else 0.0,
            "currency_note": "多币种演示按各自币种加总，未做折算",
        },
    }


def seed_demo_finance(order_id: int) -> dict[str, Any]:
    """为一笔订单写入演示收付 + 退税台账（幂等：已有收付则只补退税）。"""
    ensure_db()
    with get_conn() as conn:
        order = _get_order(conn, order_id)
        if not order:
            raise LookupError("订单不存在")
        expected = _order_expected_amount(order)
        existing_pay = fetchone(
            conn,
            "SELECT COUNT(*) AS c FROM payment_records WHERE order_id=?",
            (order_id,),
        )
        payments_created: list[dict[str, Any]] = []
        if int((existing_pay or {}).get("c") or 0) == 0 and expected > 0:
            # 30% 预付 + 70% 尾款（演示核销进度：先预付，再可补尾款）
            advance = round(expected * 0.3, 2)
            balance = round(expected - advance, 2)
            for amt, note_day in ((advance, date.today().isoformat()),):
                pid = execute(
                    conn,
                    """
                    INSERT INTO payment_records
                      (tenant_id, order_id, direction, amount, currency, value_date, matched, fx_rate)
                    VALUES (?, ?, 'in', ?, ?, ?, 0, 1.0)
                    """,
                    (
                        TENANT_ID,
                        order_id,
                        amt,
                        order.get("currency") or "USD",
                        note_day,
                    ),
                )
                payments_created.append(
                    fetchone(conn, "SELECT * FROM payment_records WHERE id=?", (pid,)) or {}
                )
            # 预留尾款提示写在结算里；可选第二笔已收尾款由 UI 录入
            _ = balance

        existing_rebate = fetchone(
            conn,
            "SELECT * FROM tax_rebate_claims WHERE order_id=? ORDER BY id DESC LIMIT 1",
            (order_id,),
        )
        rebate: dict[str, Any] | None
        if existing_rebate:
            rebate = existing_rebate
            rebate["status"] = _normalize_rebate_status(rebate.get("status"))
            rebate["status_label"] = _label_rebate(rebate["status"])
        else:
            claim = _estimate_rebate_amount(conn, order)
            rid = execute(
                conn,
                """
                INSERT INTO tax_rebate_claims
                  (tenant_id, order_id, status, claim_amount, notes)
                VALUES (?, ?, 'pending', ?, ?)
                """,
                (TENANT_ID, order_id, claim, "演示：待申报出口退税"),
            )
            rebate = fetchone(conn, "SELECT * FROM tax_rebate_claims WHERE id=?", (rid,))
            assert rebate is not None
            rebate["status"] = "pending"
            rebate["status_label"] = _label_rebate("pending")

        settlement = settlement_for_order(conn, order)
        margin = margin_for_order(conn, order)

    return {
        "order_id": order_id,
        "payments_created": payments_created,
        "rebate": rebate,
        "settlement": settlement,
        "margin": margin,
    }


def finance_bundle(order_id: int) -> dict[str, Any]:
    """订单侧 P2 汇总，供前端一块渲染。"""
    ensure_db()
    with get_conn() as conn:
        order = _get_order(conn, order_id)
        if not order:
            raise LookupError("订单不存在")
        settlement = settlement_for_order(conn, order)
        payments = fetchall(
            conn,
            "SELECT * FROM payment_records WHERE order_id=? ORDER BY id",
            (order_id,),
        )
        rebates = fetchall(
            conn,
            "SELECT * FROM tax_rebate_claims WHERE order_id=? ORDER BY id",
            (order_id,),
        )
        for r in rebates:
            r["status"] = _normalize_rebate_status(r.get("status"))
            r["status_label"] = _label_rebate(r["status"])
        margin = margin_for_order(conn, order)
    return {
        "order_id": order_id,
        "order_no": order.get("order_no"),
        "settlement": settlement,
        "payments": payments,
        "rebates": rebates,
        "margin": margin,
        "rebate_states": [{"value": k, "label": v} for k, v in REBATE_STATES.items()],
    }
