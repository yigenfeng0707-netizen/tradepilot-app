"""LLM client: ModelScope open models (魔粒/免费额度) | mock, soft-fallback to rules."""
from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from ..config import Settings, get_settings


def _extract_json(content: str) -> dict[str, Any]:
    text = (content or "").strip()
    if not text:
        raise ValueError("empty LLM content")
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


class LLMClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def mode(self) -> str:
        return self.settings.effective_llm_mode

    @property
    def api_key(self) -> str:
        return self.settings.resolved_api_key

    def _models(self) -> list[str]:
        primary = self.settings.llm_model
        fallback = self.settings.llm_fallback_model
        out = [primary]
        if fallback and fallback != primary:
            out.append(fallback)
        return out

    def chat_json(
        self,
        *,
        call_point: str,
        system: str,
        user: str,
        fallback: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return (payload, meta). meta includes model/fallback/latency."""
        meta: dict[str, Any] = {
            "call_point": call_point,
            "mode": self.mode,
            "provider": self.settings.provider_label,
            "success": False,
            "fallback_used": None,
            "model": None,
            "latency_ms": 0,
        }
        if self.mode != "api" or not self.api_key:
            meta["success"] = True
            meta["fallback_used"] = "mock"
            meta["model"] = "mock"
            meta["provider"] = "mock"
            return fallback, meta

        start = time.perf_counter()
        last_error = ""
        for model in self._models():
            try:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
                # 魔搭部分开源模型不稳支持 response_format；靠提示 + 解析兜底
                body = {
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": system
                            + "\nYou MUST reply with a single JSON object only. No markdown fences.",
                        },
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 2048,
                }
                with httpx.Client(timeout=self.settings.llm_timeout_sec) as client:
                    resp = client.post(
                        f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                        headers=headers,
                        json=body,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                choice = (data.get("choices") or [{}])[0]
                message = choice.get("message") or choice.get("delta") or {}
                content = message.get("content") or ""
                if not content and message.get("reasoning_content"):
                    # 少数思考模型把正文放别处；仍尝试从 reasoning 抽 JSON
                    content = message.get("reasoning_content") or ""
                parsed = _extract_json(content)
                meta["success"] = True
                meta["model"] = data.get("model") or model
                meta["latency_ms"] = int((time.perf_counter() - start) * 1000)
                usage = data.get("usage") or {}
                meta["prompt_tokens"] = usage.get("prompt_tokens")
                meta["completion_tokens"] = usage.get("completion_tokens")
                meta["provider"] = self.settings.provider_label
                return parsed, meta
            except Exception as exc:  # noqa: BLE001 — demo: soft fallback
                last_error = f"{model}: {exc}"[:240]
                continue

        meta["success"] = False
        meta["fallback_used"] = "rules"
        meta["error"] = last_error
        meta["latency_ms"] = int((time.perf_counter() - start) * 1000)
        return fallback, meta
