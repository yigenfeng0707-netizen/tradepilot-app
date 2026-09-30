"""TradePilot FastAPI entry — P1 + P2 demo API + static frontend."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Allow `uvicorn backend.app.main:app` from tradepilot-app/
APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
ROOT = BACKEND_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.db import fetchall, get_conn  # noqa: E402
from app.services import finance as finance_svc  # noqa: E402  # services/finance.py
from app.services.pipeline import (  # noqa: E402
    ensure_db,
    get_order_bundle,
    load_sample_po,
    load_sample_po_image,
    run_pipeline,
)

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list + ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND = ROOT / "frontend"


@app.on_event("startup")
def _startup() -> None:
    ensure_db()


class TextPipelineRequest(BaseModel):
    text: str = Field(..., min_length=20, description="PO 纯文本")
    filename: str = "pasted-po.txt"


class PaymentCreate(BaseModel):
    order_id: int
    amount: float = Field(..., gt=0)
    direction: Literal["in", "out"] = "in"
    currency: str | None = None
    value_date: str | None = None
    fx_rate: float | None = None


class RebateCreate(BaseModel):
    order_id: int
    claim_amount: float | None = None
    status: str = "pending"
    notes: str | None = None


class RebateUpdate(BaseModel):
    status: str | None = None
    claim_amount: float | None = None
    notes: str | None = None


@app.get("/api/health")
def health() -> dict:
    s = get_settings()
    real = s.real_llm_ready
    provider = s.provider_label if real else "mock"
    if real and provider == "modelscope":
        message = f"魔搭开源模型已就绪 · {s.llm_model}"
    elif real:
        message = f"过渡模型已就绪 · {s.llm_model}"
    else:
        message = "规则引擎可演示；配置 MODELSCOPE_API_KEY 后走魔搭真模型"
    return {
        "ok": True,
        "app": s.app_name,
        "llm_mode": s.effective_llm_mode,
        "llm_provider": provider,
        "llm_model": s.llm_model if real else "mock",
        "llm_configured": real,
        "demo_ready": s.demo_ready,
        "real_llm_ready": real,
        "message": message,
    }


@app.post("/api/orders/sample")
def run_sample() -> dict:
    text, name = load_sample_po()
    return run_pipeline(raw_text=text, original_filename=name)


@app.post("/api/orders/sample-image")
def run_sample_image() -> dict:
    path = load_sample_po_image()
    return run_pipeline(source_path=path, original_filename=path.name)


@app.post("/api/orders/pipeline/text")
def run_text(body: TextPipelineRequest) -> dict:
    return run_pipeline(raw_text=body.text, original_filename=body.filename)


@app.post("/api/orders/pipeline")
async def run_upload(file: UploadFile = File(...)) -> dict:
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "空文件")
    name = file.filename or "upload.bin"
    suffix = Path(name).suffix.lower() or ".bin"
    tmp = settings.upload_dir / f"_tmp_{datetime_stamp()}{suffix}"
    tmp.write_bytes(raw)
    try:
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".pdf"}:
            return run_pipeline(source_path=tmp, original_filename=name)
        try:
            text = raw.decode("utf-8")
            return run_pipeline(raw_text=text, original_filename=name)
        except UnicodeDecodeError:
            return run_pipeline(source_path=tmp, original_filename=name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        if tmp.exists() and tmp.name.startswith("_tmp_"):
            try:
                tmp.unlink()
            except OSError:
                pass


def datetime_stamp() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S%f")


@app.get("/api/orders/{order_id}")
def order_detail(order_id: int) -> dict:
    bundle = get_order_bundle(order_id)
    if not bundle:
        raise HTTPException(404, "订单不存在")
    # parse json fields for frontend
    for d in bundle.get("generated_docs") or []:
        if isinstance(d.get("fields_json"), str):
            try:
                d["fields"] = json.loads(d["fields_json"])
            except json.JSONDecodeError:
                d["fields"] = {}
    for c in bundle.get("consistency_checks") or []:
        if isinstance(c.get("diffs_json"), str):
            try:
                c["diffs"] = json.loads(c["diffs_json"])
            except json.JSONDecodeError:
                c["diffs"] = []
    if bundle.get("contract") and isinstance(bundle["contract"].get("risk_alerts_json"), str):
        try:
            bundle["contract"]["risk_alerts"] = json.loads(bundle["contract"]["risk_alerts_json"])
        except json.JSONDecodeError:
            bundle["contract"]["risk_alerts"] = []
    return bundle


@app.get("/api/orders")
def list_orders(limit: int = 20) -> dict:
    with get_conn() as conn:
        rows = fetchall(
            conn,
            "SELECT id, order_no, po_no, currency, trade_term, destination, total_amount, status, created_at "
            "FROM trade_orders ORDER BY id DESC LIMIT ?",
            (limit,),
        )
    return {"items": rows}


@app.get("/api/files")
def read_generated_file(path: str) -> FileResponse:
    """Read files only under data/outputs for preview."""
    target = Path(path).resolve()
    root = (settings.output_dir).resolve()
    if not str(target).startswith(str(root)):
        raise HTTPException(403, "路径越权")
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(target)


# ---------- P2: 收付汇 / 退税 / 毛利 ----------


@app.get("/api/finance/payments")
def api_list_payments(order_id: int | None = None, limit: int = 50) -> dict:
    return {"items": finance_svc.list_payments(order_id=order_id, limit=limit)}


@app.post("/api/finance/payments")
def api_create_payment(body: PaymentCreate) -> dict:
    try:
        return finance_svc.create_payment(
            order_id=body.order_id,
            amount=body.amount,
            direction=body.direction,
            currency=body.currency,
            value_date=body.value_date,
            fx_rate=body.fx_rate,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/finance/settlement/{order_id}")
def api_settlement(order_id: int) -> dict:
    try:
        return finance_svc.get_settlement(order_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/finance/rebates")
def api_list_rebates(order_id: int | None = None, limit: int = 50) -> dict:
    return {"items": finance_svc.list_rebates(order_id=order_id, limit=limit)}


@app.post("/api/finance/rebates")
def api_create_rebate(body: RebateCreate) -> dict:
    try:
        return finance_svc.create_rebate(
            order_id=body.order_id,
            claim_amount=body.claim_amount,
            status=body.status,
            notes=body.notes,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.patch("/api/finance/rebates/{rebate_id}")
def api_update_rebate(rebate_id: int, body: RebateUpdate) -> dict:
    try:
        return finance_svc.update_rebate(
            rebate_id,
            status=body.status,
            claim_amount=body.claim_amount,
            notes=body.notes,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/finance/margin")
def api_margin_report(order_id: int | None = None, limit: int = 30) -> dict:
    try:
        return finance_svc.margin_report(order_id=order_id, limit=limit)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/finance/orders/{order_id}")
def api_finance_bundle(order_id: int) -> dict:
    try:
        return finance_svc.finance_bundle(order_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/finance/demo-seed/{order_id}")
def api_finance_seed(order_id: int) -> dict:
    """一键写入演示收付（30% 预付）+ 待申报退税台账。"""
    try:
        return finance_svc.seed_demo_finance(order_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/")
def index() -> FileResponse:
    index_html = FRONTEND / "index.html"
    if not index_html.exists():
        raise HTTPException(500, "frontend/index.html 缺失")
    return FileResponse(index_html)


if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")
