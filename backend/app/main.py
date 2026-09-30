"""TradePilot FastAPI entry — P1 demo API + static frontend."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

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
from app.services.pipeline import (  # noqa: E402
    ensure_db,
    get_order_bundle,
    load_sample_po,
    load_sample_po_image,
    run_pipeline,
)

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
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


@app.get("/")
def index() -> FileResponse:
    index_html = FRONTEND / "index.html"
    if not index_html.exists():
        raise HTTPException(500, "frontend/index.html 缺失")
    return FileResponse(index_html)


if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")
