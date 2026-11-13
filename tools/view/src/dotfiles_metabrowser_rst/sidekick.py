from __future__ import annotations

import asyncio
import io

from starlette.requests import Request
from starlette.responses import JSONResponse

from metabrowser import (
    ArtifactDecompressionLimitError,
    ContentReadError,
    ContentRef,
    read_content_window,
    resolve_content,
)


MAX_RST_BYTES = 2 * 1024 * 1024
RST_EXTENSIONS = frozenset({".rst"})


def _render_document(source: str, source_path: str) -> dict[str, object]:
    from docutils.core import publish_parts

    warnings = io.StringIO()
    parts = publish_parts(
        source=source,
        source_path=source_path,
        writer_name="html5",
        settings_overrides={
            # A browser view should never make a document read arbitrary local files
            # or inject active markup outside Metabrowser's own trust controls.
            "file_insertion_enabled": False,
            "raw_enabled": False,
            "report_level": 2,
            "halt_level": 5,
            "warning_stream": warnings,
            "embed_stylesheet": False,
            "stylesheet_path": None,
            "syntax_highlight": "short",
        },
    )
    return {
        "html": parts["html_body"],
        "title": parts.get("title", ""),
        "warnings": [line for line in warnings.getvalue().splitlines() if line],
    }


async def _read_document(ref: ContentRef) -> tuple[str | None, bool]:
    try:
        window = await read_content_window(ref, max_bytes=MAX_RST_BYTES)
    except ArtifactDecompressionLimitError:
        return None, True
    if window.has_more:
        return None, True
    try:
        return window.data.decode("utf-8"), False
    except UnicodeDecodeError as exc:
        raise ValueError("reStructuredText input is not valid UTF-8") from exc


async def rendered_handler(request: Request) -> JSONResponse:
    raw_path = request.query_params.get("path", "")
    try:
        ref = await resolve_content(raw_path)
        if ref is None:
            return JSONResponse({"error": "Not found", "path": raw_path}, status_code=404)
        if ref.logical_ext not in RST_EXTENSIONS:
            return JSONResponse(
                {"error": "Unsupported extension", "path": raw_path, "ext": ref.logical_ext},
                status_code=400,
            )
        source, truncated = await _read_document(ref)
        rendered = (
            {"html": "", "title": "", "warnings": []}
            if truncated or source is None
            else await asyncio.to_thread(_render_document, source, ref.identity)
        )
    except ContentReadError as exc:
        return JSONResponse(
            {"error": str(exc), "code": exc.code, "path": raw_path},
            status_code=exc.http_status,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc), "path": raw_path}, status_code=400)

    return JSONResponse(
        {
            "type": "rst",
            "path": ref.identity,
            "ext": ref.logical_ext,
            "mtime_hash": ref.fingerprint,
            "size": ref.stored_size,
            "truncated": truncated,
            **rendered,
        }
    )
