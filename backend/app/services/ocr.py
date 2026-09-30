"""Local OCR for scanned PO images → text for ModelScope LLM extraction."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _engine():
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def ocr_image(path: Path | str) -> dict:
    """Return {text, lines, engine, elapse}."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    engine = _engine()
    result, elapse = engine(str(path))
    lines: list[str] = []
    if result:
        for row in result:
            if len(row) >= 2 and row[1]:
                lines.append(str(row[1]))
    text = "\n".join(lines)
    # 常见 OCR 误识：ClF / ClF → CIF
    text = text.replace("ClF", "CIF").replace("ClF", "CIF")
    return {
        "text": text,
        "lines": lines,
        "engine": "rapidocr-onnxruntime",
        "elapse": elapse,
    }
