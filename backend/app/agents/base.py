"""Thin agent facades — dispatcher / contract / docs."""
from __future__ import annotations

from ..services.pipeline import run_pipeline


class DispatcherAgent:
    name = "dispatcher"

    def run_p1(self, **kwargs):
        return run_pipeline(**kwargs)


class ContractAgent:
    name = "contract"


class DocsAgent:
    name = "docs"
