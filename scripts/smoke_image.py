"""Smoke: sample PO image → OCR → ModelScope LLM → CLOSED_LOOP_OK."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BACKEND))

from app.services.pipeline import load_sample_po_image, run_pipeline  # noqa: E402


def main() -> int:
    path = load_sample_po_image()
    result = run_pipeline(source_path=path, original_filename=path.name)
    summary = {
        "order_no": result.get("order_no"),
        "ok": result.get("ok"),
        "extractor": (result.get("extraction") or {}).get("extractor"),
        "read_meta": result.get("read_meta"),
        "llm_mode": result.get("llm_mode"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if result.get("ok") and (result.get("read_meta") or {}).get("source_kind") == "image_ocr":
        print("IMAGE_LOOP_OK")
        return 0
    print("IMAGE_LOOP_FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
