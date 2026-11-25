"""Thin LangFuse wrapper used to trace every test-generation call and every
human review decision.

Safe to import and use even when LangFuse is not installed or not
configured: `Tracer.span()` then yields a handle backed by nothing but a
local uuid, and every LangFuse call is wrapped in try/except so a transient
network issue never breaks the pipeline.
"""
from __future__ import annotations

import contextlib
import uuid
from typing import Any, Dict, Optional

from .config import Settings


class _SpanHandle:
    def __init__(self, trace_id: str, langfuse_span: Any = None):
        self.trace_id = trace_id
        self._langfuse_span = langfuse_span
        self.output: Dict[str, Any] = {}

    def set_output(self, output: Dict[str, Any]) -> None:
        self.output = output
        if self._langfuse_span is not None:
            try:
                self._langfuse_span.end(output=output)
            except Exception:
                pass


class Tracer:
    def __init__(self, settings: Optional[Settings] = None):
        self._settings = settings or Settings.from_env()
        self._client = None
        if self._settings.langfuse_public_key and self._settings.langfuse_secret_key:
            try:
                from langfuse import Langfuse

                self._client = Langfuse(
                    public_key=self._settings.langfuse_public_key,
                    secret_key=self._settings.langfuse_secret_key,
                    host=self._settings.langfuse_host,
                )
            except Exception:
                self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @contextlib.contextmanager
    def span(self, name: str, metadata: Optional[Dict[str, Any]] = None):
        trace_id = uuid.uuid4().hex
        langfuse_span = None
        if self._client is not None:
            try:
                trace = self._client.trace(name=name, metadata=metadata or {})
                trace_id = trace.id
                langfuse_span = trace.span(name=name, metadata=metadata or {})
            except Exception:
                langfuse_span = None

        handle = _SpanHandle(trace_id=trace_id, langfuse_span=langfuse_span)
        try:
            yield handle
        finally:
            if langfuse_span is not None and not handle.output:
                try:
                    langfuse_span.end()
                except Exception:
                    pass

    def log_event(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
        if self._client is None:
            return None
        try:
            trace = self._client.trace(name=name, metadata=metadata or {})
            return trace.id
        except Exception:
            return None

    def flush(self) -> None:
        if self._client is not None:
            try:
                self._client.flush()
            except Exception:
                pass


tracer = Tracer()
