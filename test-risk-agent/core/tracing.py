"""Thin LangFuse wrapper used to trace every test-generation call and every
human review decision.

Written against the current (OpenTelemetry-based) `langfuse` SDK (v3+):
`Langfuse.start_as_current_observation(...)` as a context manager, not the
older `.trace()/.span()` StatefulTraceClient API, which Langfuse Cloud has
since deprecated and removed - see `DECISIONS.md` for how that was caught.

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
                self._langfuse_span.update(output=output)
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
        observation_cm = None
        if self._client is not None:
            try:
                observation_cm = self._client.start_as_current_observation(
                    name=name, as_type="span", metadata=metadata or {}
                )
                langfuse_span = observation_cm.__enter__()
                trace_id = langfuse_span.trace_id
            except Exception:
                observation_cm = None
                langfuse_span = None

        handle = _SpanHandle(trace_id=trace_id, langfuse_span=langfuse_span)
        try:
            yield handle
        finally:
            if observation_cm is not None:
                try:
                    observation_cm.__exit__(None, None, None)
                except Exception:
                    pass

    def log_event(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
        if self._client is None:
            return None
        try:
            with self._client.start_as_current_observation(
                name=name, as_type="span", metadata=metadata or {}
            ) as span:
                return span.trace_id
        except Exception:
            return None

    def trace_url(self, trace_id: Optional[str]) -> Optional[str]:
        if self._client is None or not trace_id:
            return None
        try:
            return self._client.get_trace_url(trace_id=trace_id)
        except Exception:
            return None

    def flush(self) -> None:
        if self._client is not None:
            try:
                self._client.flush()
            except Exception:
                pass


tracer = Tracer()
