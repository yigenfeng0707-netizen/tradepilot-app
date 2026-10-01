"""TradePilot FastAPI entry — P1 + P2 + P2+ infra (JWT / Celery / MinIO)."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
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

from app.auth import login_and_issue_token, require_auth  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import fetchall, get_conn  # noqa: E402
from app.services import finance as finance_svc  # noqa: E402
from app.services import storage as object_store  # noqa: E402
from app.services.pipeline import (  # noqa: E402
    ensure_db,
    get_order_bundle,
    load_sample_po,
    load_sample_po_image,
    run_pipeline,
)

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.3.0")
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
    async_mode: bool = Field(False, alias="async", description="Celery 异步（需 CELERY_ENABLED=1）")

    model_config = {"populate_by_name": True}


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


class LoginRequest(BaseModel):
    username: str = "demo"
    password: str = "demo"


def _maybe_enqueue(
    *,
    want_async: bool,
    raw_text: str | None = None,
    source_path: Path | None = None,
    original_filename: str | None = None,
) -> dict[str, Any] | None:
    if not want_async:
        return None
    from app.tasks import enqueue_pipeline

    return enqueue_pipeline(
        raw_text=raw_text,
        source_path=str(source_path) if source_path else None,
        original_filename=original_filename,
    )


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
    celery_status = {"enabled": s.celery_on, "broker_up": False}
    if s.celery_on:
        try:
            from app.tasks import celery_available

            celery_status["broker_up"] = celery_available()
        except Exception:  # noqa: BLE001
            celery_status["broker_up"] = False
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
        "auth_required": s.auth_required,
        "celery": celery_status,
        "storage": object_store.storage_status(),
    }


@app.post("/api/auth/login")
def api_login(body: LoginRequest) -> dict:
    s = get_settings()
    if not (s.jwt_secret or "").strip():
        raise HTTPException(400, "JWT_SECRET 未配置；本地 Demo 可保持 AUTH_DISABLED=1")
    return login_and_issue_token(body.username, body.password)


@app.get("/api/auth/me")
def api_me(user: dict = Depends(require_auth)) -> dict:
    return {"user": user, "auth_required": get_settings().auth_required}


@app.post("/api/orders/sample")
def run_sample(
    async_mode: bool = Query(False, alias="async"),
    _user: dict = Depends(require_auth),
) -> dict:
    text, name = load_sample_po()
    queued = _maybe_enqueue(want_async=async_mode, raw_text=text, original_filename=name)
    if queued:
        return queued
    return run_pipeline(raw_text=text, original_filename=name)


@app.post("/api/orders/sample-image")
def run_sample_image(
    async_mode: bool = Query(False, alias="async"),
    _user: dict = Depends(require_auth),
) -> dict:
    path = load_sample_po_image()
    queued = _maybe_enqueue(
        want_async=async_mode,
        source_path=path,
        original_filename=path.name,
    )
    if queued:
        return queued
    return run_pipeline(source_path=path, original_filename=path.name)


@app.post("/api/orders/pipeline/text")
def run_text(body: TextPipelineRequest, _user: dict = Depends(require_auth)) -> dict:
    queued = _maybe_enqueue(
        want_async=body.async_mode,
        raw_text=body.text,
        original_filename=body.filename,
    )
    if queued:
        return queued
    return run_pipeline(raw_text=body.text, original_filename=body.filename)


@app.post("/api/orders/pipeline")
async def run_upload(
    file: UploadFile = File(...),
    async_mode: bool = Query(False, alias="async"),
    _user: dict = Depends(require_auth),
) -> dict:
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "空文件")
    name = file.filename or "upload.bin"
    suffix = Path(name).suffix.lower() or ".bin"
    stamp = datetime_stamp()
    tmp = settings.upload_dir / f"_tmp_{stamp}{suffix}"
    tmp.write_bytes(raw)
    try:
        if async_mode:
            persist = settings.upload_dir / f"_async_{stamp}{suffix}"
            tmp.rename(persist)
            queued = _maybe_enqueue(
                want_async=True,
                source_path=persist,
                original_filename=name,
            )
            if queued:
                return queued
            # Celery down → fall through to sync using persist
            tmp = persist
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


@app.get("/api/tasks/{task_id}")
def api_task_status(task_id: str, _user: dict = Depends(require_auth)) -> dict:
    from app.tasks import task_status

    return task_status(task_id)


@app.websocket("/ws/tasks/{task_id}")
async def ws_task_progress(websocket: WebSocket, task_id: str) -> None:
    """Light progress channel — polls Celery result every second."""
    await websocket.accept()
    try:
        from app.tasks import task_status

        for _ in range(600):
            status = task_status(task_id)
            await websocket.send_json(status)
            if status.get("ready"):
                break
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001
        try:
            await websocket.send_json({"task_id": task_id, "status": "ERROR", "error": str(exc)})
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass


@app.get("/api/orders/{order_id}")
def order_detail(order_id: int) -> dict:
    bundle = get_order_bundle(order_id)
    if not bundle:
        raise HTTPException(404, "订单不存在")
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
def read_generated_file(path: str, _user: dict = Depends(require_auth)) -> Response:
    """Read files only under data/outputs for preview; MinIO fallback if local missing."""
    target = Path(path).resolve()
    root = (settings.output_dir).resolve()
    if not str(target).startswith(str(root)):
        raise HTTPException(403, "路径越权")
    if target.exists() and target.is_file():
        return FileResponse(target)
    # try MinIO
    key = object_store.object_key_for_path(target)
    data = object_store.get_object_bytes(key)
    if data is not None:
        return Response(content=data, media_type="application/octet-stream")
    raise HTTPException(404, "文件不存在")


# ---------- P2: 收付汇 / 退税 / 毛利 ----------


@app.get("/api/finance/payments")
def api_list_payments(order_id: int | None = None, limit: int = 50) -> dict:
    return {"items": finance_svc.list_payments(order_id=order_id, limit=limit)}


@app.post("/api/finance/payments")
def api_create_payment(body: PaymentCreate, _user: dict = Depends(require_auth)) -> dict:
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
def api_create_rebate(body: RebateCreate, _user: dict = Depends(require_auth)) -> dict:
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
def api_update_rebate(rebate_id: int, body: RebateUpdate, _user: dict = Depends(require_auth)) -> dict:
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
def api_finance_seed(order_id: int, _user: dict = Depends(require_auth)) -> dict:
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
