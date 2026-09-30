#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P1 closed-loop smoke: must print CLOSED_LOOP_OK."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.pipeline import load_sample_po, run_pipeline  # noqa: E402


def main() -> int:
    text, name = load_sample_po()
    result = run_pipeline(raw_text=text, original_filename=name)
    fields = result["extraction"]["fields"]
    checks = [
        ("buyer", (fields.get("buyer") or "").upper().find("ABC") >= 0),
        ("qty", float(fields.get("qty") or 0) == 5000),
        ("unit_price", abs(float(fields.get("unit_price") or 0) - 3.2) < 0.001),
        ("total", abs(float(fields.get("total_amount") or 0) - 16000) < 0.01),
        ("trade_term", str(fields.get("trade_term") or "").upper().startswith("CIF")),
        ("contract", bool(result.get("contract")),),
        ("docs", len(result.get("generated_docs") or []) >= 3),
        ("consistency", bool(result.get("consistency", {}).get("passed"))),
        ("ok_flag", bool(result.get("ok"))),
    ]
    failed = [name for name, ok in checks if not ok]
    summary = {
        "order_no": result.get("order_no"),
        "extractor": result["extraction"].get("extractor"),
        "llm_mode": result.get("llm_mode"),
        "failed": failed,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if failed:
        print("SMOKE_FAILED")
        return 1
    print("CLOSED_LOOP_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
