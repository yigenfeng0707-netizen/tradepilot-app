"""P1 end-to-end pipeline: upload PO → parse → contract → PI/CI/PL → check."""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..db import execute, fetchall, fetchone, get_conn, init_db
from .audit import append_audit
from .extractor import extract_po
from .generator import (
    build_context,
    consistency_check,
    detect_risks,
    render_contract,
    render_docs,
    write_output,
)
from .llm import LLMClient
from .pdf_export import export_bundle_pdfs
from . import storage as object_store


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9\-]+", "-", s).strip("-")[:40] or "order"


def _read_upload(path: Path) -> tuple[str, dict[str, Any]]:
    """Return (text, read_meta). Images go RapidOCR → text for 魔搭 LLM."""
    suffix = path.suffix.lower()
    meta: dict[str, Any] = {"source_kind": "text", "path": str(path)}
    if suffix in {".txt", ".md", ".csv"}:
        return path.read_text(encoding="utf-8", errors="ignore"), meta
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
        from .ocr import ocr_image

        ocr = ocr_image(path)
        meta.update(
            {
                "source_kind": "image_ocr",
                "ocr_engine": ocr.get("engine"),
                "ocr_elapse": ocr.get("elapse"),
                "ocr_lines": len(ocr.get("lines") or []),
            }
        )
        return ocr.get("text") or "", meta
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            meta["source_kind"] = "pdf_text"
            if text.strip():
                return text, meta
        except Exception:
            pass
        # 扫描件 PDF：尝试首页渲染 OCR（无渲染能力则返回空，由上层报错）
        meta["source_kind"] = "pdf_empty"
        return "", meta
    return path.read_text(encoding="utf-8", errors="ignore"), meta


def ensure_db() -> None:
    settings = get_settings()
    db_file = Path(settings.database_url.replace("sqlite:///", "", 1))
    if not db_file.exists():
        init_db()
    else:
        # still ensure schema (IF NOT EXISTS)
        init_db()


def run_pipeline(
    *,
    source_path: Path | None = None,
    raw_text: str | None = None,
    original_filename: str | None = None,
    tenant_id: int = 1,
) -> dict[str, Any]:
    ensure_db()
    settings = get_settings()
    llm = LLMClient(settings)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    read_meta: dict[str, Any] = {"source_kind": "text"}

    if raw_text is None:
        if source_path is None:
            raise ValueError("source_path or raw_text required")
        raw_text, read_meta = _read_upload(source_path)
        original_filename = original_filename or source_path.name
        if not (raw_text or "").strip():
            raise ValueError("未能从文件识别出可用文本（OCR/PDF 为空）")

    stored_name = f"{ts}-{_slug(original_filename or 'po.txt')}"
    upload_path = settings.upload_dir / stored_name
    # 保留原图/原文件；文本副本另存 .ocr.txt 便于审计
    if source_path and source_path.exists() and read_meta.get("source_kind") == "image_ocr":
        upload_path = settings.upload_dir / f"{ts}-{_slug(original_filename or 'po.png')}{source_path.suffix.lower()}"
        shutil.copyfile(source_path, upload_path)
        (settings.upload_dir / f"{upload_path.stem}.ocr.txt").write_text(raw_text, encoding="utf-8")
        mime = f"image/{source_path.suffix.lower().lstrip('.') or 'png'}"
    else:
        upload_path.write_text(raw_text, encoding="utf-8")
        mime = "text/plain"

    # Optional MinIO mirror (local file always kept)
    storage_meta = object_store.put_file(upload_path)
    ocr_txt = settings.upload_dir / f"{upload_path.stem}.ocr.txt"
    if ocr_txt.exists():
        object_store.put_file(ocr_txt)

    with get_conn() as conn:
        doc_id = execute(
            conn,
            """
            INSERT INTO documents (tenant_id, doc_type, source, filename, storage_path, mime_type, status)
            VALUES (?, 'po', 'upload', ?, ?, ?, 'received')
            """,
            (tenant_id, original_filename or stored_name, str(upload_path), mime),
        )
        task_id = execute(
            conn,
            """
            INSERT INTO agent_tasks (tenant_id, task_type, agent_name, autonomy_level, status, input_json)
            VALUES (?, 'p1_pipeline', 'dispatcher', 1, 'running', ?)
            """,
            (tenant_id, json.dumps({"filename": original_filename}, ensure_ascii=False)),
        )
        append_audit(
            conn,
            tenant_id=tenant_id,
            actor="agent:dispatcher",
            action="pipeline_start",
            entity_type="document",
            entity_id=str(doc_id),
            detail={"task_id": task_id},
        )

        # --- parse ---
        extracted = extract_po(raw_text, llm=llm)
        fields = extracted["fields"]
        conf = extracted["confidence"]
        execute(
            conn,
            """
            INSERT INTO document_extractions (document_id, extractor, raw_text, fields_json, confidence_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                doc_id,
                extracted["extractor"],
                raw_text[:20000],
                json.dumps(fields, ensure_ascii=False),
                json.dumps(conf, ensure_ascii=False),
            ),
        )
        execute(conn, "UPDATE documents SET status='parsed' WHERE id=?", (doc_id,))
        execute(
            conn,
            """
            INSERT INTO llm_call_logs (tenant_id, task_id, call_point, model, latency_ms, success, fallback_used)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tenant_id,
                task_id,
                "LLM-2",
                (extracted.get("llm_meta") or {}).get("model"),
                (extracted.get("llm_meta") or {}).get("latency_ms") or 0,
                1 if (extracted.get("llm_meta") or {}).get("success") else 0,
                (extracted.get("llm_meta") or {}).get("fallback_used"),
            ),
        )
        append_audit(
            conn,
            tenant_id=tenant_id,
            actor="agent:contract",
            action="extract",
            entity_type="document",
            entity_id=str(doc_id),
            detail={"extractor": extracted["extractor"], "po_no": fields.get("po_no")},
        )

        # --- parties & order ---
        buyer_name = fields.get("buyer") or "Unknown Buyer"
        seller_name = fields.get("seller") or "杭州余杭光电有限公司"
        buyer = fetchone(
            conn,
            "SELECT * FROM parties WHERE tenant_id=? AND party_type='buyer' AND name=?",
            (tenant_id, buyer_name),
        )
        if not buyer:
            buyer_id = execute(
                conn,
                "INSERT INTO parties (tenant_id, party_type, name, name_en) VALUES (?, 'buyer', ?, ?)",
                (tenant_id, buyer_name, buyer_name),
            )
            buyer = fetchone(conn, "SELECT * FROM parties WHERE id=?", (buyer_id,))
        seller = fetchone(
            conn,
            "SELECT * FROM parties WHERE tenant_id=? AND party_type='seller' ORDER BY id LIMIT 1",
            (tenant_id,),
        )
        if not seller:
            seller_id = execute(
                conn,
                "INSERT INTO parties (tenant_id, party_type, name, name_en, country) VALUES (?, 'seller', ?, ?, 'CN')",
                (tenant_id, seller_name, seller_name),
            )
            seller = fetchone(conn, "SELECT * FROM parties WHERE id=?", (seller_id,))

        po_no = fields.get("po_no") or f"PO-{ts}"
        order_no = f"SO-{ts}"
        trade_term_raw = fields.get("trade_term") or ""
        trade_term = trade_term_raw
        destination = fields.get("destination")
        if " " in trade_term_raw and trade_term_raw.split()[0] in {"CIF", "FOB", "CFR", "EXW", "DDP"}:
            parts = trade_term_raw.split(None, 1)
            trade_term = parts[0]
            destination = destination or (parts[1] if len(parts) > 1 else None)

        total = float(fields.get("total_amount") or 0)
        order_id = execute(
            conn,
            """
            INSERT INTO trade_orders
              (tenant_id, order_no, po_no, buyer_id, seller_id, currency, trade_term, destination,
               payment_terms, total_amount, status, source_doc_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?)
            """,
            (
                tenant_id,
                order_no,
                po_no,
                buyer["id"],
                seller["id"],
                fields.get("currency") or "USD",
                trade_term,
                destination,
                fields.get("payment_terms"),
                total,
                doc_id,
            ),
        )
        qty = float(fields.get("qty") or 0)
        unit_price = float(fields.get("unit_price") or 0)
        packages = int(fields.get("packages") or max(1, int(qty // 50)))
        line_id = execute(
            conn,
            """
            INSERT INTO order_line_items
              (order_id, line_no, product_name, product_name_en, hs_code, qty, unit, unit_price, amount,
               packages, gross_weight_kg, net_weight_kg, volume_cbm)
            VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                fields.get("product_name") or "Merchandise",
                fields.get("product_name") or "Merchandise",
                "9405110000",
                qty,
                fields.get("unit") or "PCS",
                unit_price,
                total,
                packages,
                packages * 12.5,
                packages * 11.0,
                round(packages * 0.08, 3),
            ),
        )
        execute(conn, "UPDATE agent_tasks SET order_id=? WHERE id=?", (order_id, task_id))

        order = fetchone(conn, "SELECT * FROM trade_orders WHERE id=?", (order_id,))
        line = fetchone(conn, "SELECT * FROM order_line_items WHERE id=?", (line_id,))
        bank = fetchone(
            conn,
            "SELECT * FROM bank_accounts WHERE tenant_id=? AND is_default=1 ORDER BY id LIMIT 1",
            (tenant_id,),
        )
        hs = fetchone(conn, "SELECT * FROM hs_codes WHERE code=?", ("9405110000",))
        risks = detect_risks(order, settings)
        ctx = build_context(
            order,
            line,
            {
                "bank": bank,
                "buyer": buyer,
                "seller": seller,
                "risk_alerts": risks,
                "declare_elements": (hs or {}).get("declare_elements"),
            },
        )

        # --- contract ---
        contract = render_contract(ctx, llm=llm)
        out_dir = settings.output_dir / order_no
        contract_path = write_output(out_dir / "contract_zh_en.md", contract["body_md"])
        contract_id = execute(
            conn,
            """
            INSERT INTO contracts
              (tenant_id, order_id, contract_no, lang, body_md, risk_alerts_json, status, storage_path)
            VALUES (?, ?, ?, 'zh_en', ?, ?, 'pending_confirm', ?)
            """,
            (
                tenant_id,
                order_id,
                f"SC-{order_no}",
                contract["body_md"],
                json.dumps(risks, ensure_ascii=False),
                contract_path,
            ),
        )
        for key, content in [
            ("payment", order.get("payment_terms") or ""),
            ("shipping", f"{order.get('trade_term')} {order.get('destination') or ''}".strip()),
            ("penalty", "Any party in breach shall compensate direct losses."),
            ("marking", f"Shipping Mark: {po_no} / JEBEL ALI / MADE IN CHINA"),
        ]:
            execute(
                conn,
                "INSERT INTO contract_clauses (contract_id, clause_key, content, is_risk) VALUES (?, ?, ?, ?)",
                (contract_id, key, content, 1 if key == "payment" and risks else 0),
            )
        execute(
            conn,
            """
            INSERT INTO llm_call_logs (tenant_id, task_id, call_point, model, latency_ms, success, fallback_used)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tenant_id,
                task_id,
                "LLM-3",
                (contract.get("llm_meta") or {}).get("model"),
                (contract.get("llm_meta") or {}).get("latency_ms") or 0,
                1 if (contract.get("llm_meta") or {}).get("success") else 0,
                (contract.get("llm_meta") or {}).get("fallback_used"),
            ),
        )
        append_audit(
            conn,
            tenant_id=tenant_id,
            actor="agent:contract",
            action="generate",
            entity_type="contract",
            entity_id=str(contract_id),
            detail={"generator": contract["generator"], "risks": risks},
        )

        # --- one-source many docs ---
        docs = render_docs(ctx)
        generated = []
        for key, doc in docs.items():
            path = write_output(out_dir / f"{key}.md", doc["body_md"])
            gid = execute(
                conn,
                """
                INSERT INTO generated_docs
                  (tenant_id, order_id, contract_id, doc_type, doc_no, fields_json, storage_path, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'draft')
                """,
                (
                    tenant_id,
                    order_id,
                    contract_id,
                    doc["doc_type"],
                    f"{doc['doc_type'].upper()}-{order_no}",
                    json.dumps(doc["fields"], ensure_ascii=False),
                    path,
                ),
            )
            generated.append(
                {
                    "id": gid,
                    "doc_type": doc["doc_type"],
                    "path": path,
                    "preview": doc["body_md"][:800],
                }
            )

        # --- PDF 精美出单 ---
        pdf_paths: dict[str, str] = {}
        try:
            pdf_paths = export_bundle_pdfs(
                out_dir,
                contract_md=contract["body_md"],
                docs=docs,
            )
            for _k, p in list(pdf_paths.items()):
                object_store.put_file(p)
            append_audit(
                conn,
                tenant_id=tenant_id,
                actor="agent:docs",
                action="export_pdf",
                entity_type="order",
                entity_id=str(order_id),
                detail={"pdfs": list(pdf_paths.keys()), "storage": object_store.storage_status()},
            )
        except Exception as pdf_exc:  # noqa: BLE001
            append_audit(
                conn,
                tenant_id=tenant_id,
                actor="agent:docs",
                action="export_pdf_failed",
                entity_type="order",
                entity_id=str(order_id),
                detail={"error": str(pdf_exc)[:200]},
            )

        for item in generated:
            pdf_key = {
                "pi": "pi",
                "ci": "ci",
                "pl": "pl",
                "customs_elements": "customs",
            }.get(item["doc_type"], item["doc_type"])
            if pdf_key in pdf_paths:
                item["pdf_path"] = pdf_paths[pdf_key]

        check = consistency_check(order, line, docs)
        execute(
            conn,
            """
            INSERT INTO consistency_checks (order_id, passed, summary, diffs_json)
            VALUES (?, ?, ?, ?)
            """,
            (order_id, 1 if check["passed"] else 0, check["summary"], json.dumps(check["diffs"], ensure_ascii=False)),
        )
        append_audit(
            conn,
            tenant_id=tenant_id,
            actor="agent:docs",
            action="consistency_check",
            entity_type="order",
            entity_id=str(order_id),
            detail=check,
        )

        status = "done" if check["passed"] else "blocked"
        execute(
            conn,
            """
            UPDATE agent_tasks
            SET status=?, output_json=?, finished_at=datetime('now'),
                error_message=?
            WHERE id=?
            """,
            (
                status,
                json.dumps({"order_id": order_id, "passed": check["passed"]}, ensure_ascii=False),
                None if check["passed"] else check["summary"],
                task_id,
            ),
        )
        if check["passed"]:
            execute(conn, "UPDATE trade_orders SET status='confirmed' WHERE id=?", (order_id,))

        audit_rows = fetchall(
            conn,
            "SELECT id, actor, action, entity_type, entry_hash, created_at FROM audit_logs WHERE tenant_id=? ORDER BY id DESC LIMIT 8",
            (tenant_id,),
        )

        return {
            "ok": check["passed"],
            "order_id": order_id,
            "order_no": order_no,
            "po_no": po_no,
            "task_id": task_id,
            "document_id": doc_id,
            "extraction": {
                "fields": fields,
                "confidence": conf,
                "extractor": extracted["extractor"],
            },
            "contract": {
                "id": contract_id,
                "path": contract_path,
                "pdf_path": pdf_paths.get("contract"),
                "generator": contract["generator"],
                "risk_alerts": risks,
                "preview": contract["body_md"][:1500],
            },
            "generated_docs": generated,
            "pdf_paths": pdf_paths,
            "consistency": check,
            "audit_tail": audit_rows,
            "llm_mode": llm.mode,
            "llm_provider": getattr(llm.settings, "provider_label", None),
            "read_meta": read_meta,
            "storage": {**object_store.storage_status(), "upload": storage_meta},
        }


def get_order_bundle(order_id: int) -> dict[str, Any] | None:
    ensure_db()
    with get_conn() as conn:
        order = fetchone(conn, "SELECT * FROM trade_orders WHERE id=?", (order_id,))
        if not order:
            return None
        lines = fetchall(conn, "SELECT * FROM order_line_items WHERE order_id=?", (order_id,))
        contract = fetchone(conn, "SELECT * FROM contracts WHERE order_id=?", (order_id,))
        docs = fetchall(conn, "SELECT * FROM generated_docs WHERE order_id=?", (order_id,))
        checks = fetchall(
            conn,
            "SELECT * FROM consistency_checks WHERE order_id=? ORDER BY id DESC",
            (order_id,),
        )
        return {
            "order": order,
            "lines": lines,
            "contract": contract,
            "generated_docs": docs,
            "consistency_checks": checks,
        }


def load_sample_po() -> tuple[str, str]:
    settings = get_settings()
    sample = settings.samples_dir / "PO-2026-0913.txt"
    return sample.read_text(encoding="utf-8"), sample.name


def load_sample_po_image() -> Path:
    settings = get_settings()
    sample = settings.samples_dir / "PO-2026-0913.png"
    if not sample.exists():
        raise FileNotFoundError("samples/PO-2026-0913.png 缺失")
    return sample
