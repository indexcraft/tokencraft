"""
TokenCraft — by IndexCraft

FastAPI dashboard that converts files to Markdown and reports honest,
per-file token comparisons — no fabricated multipliers.

Two deployment modes, one codebase:
  - LOCAL_MODE=true  (default): folder browse/save/open-in-explorer enabled
    — meant for `run.bat`/`run.sh` on your own machine.
  - LOCAL_MODE=false: those endpoints are disabled (a hosted server has no
    business touching a visitor's filesystem). Used for the Wasmer deploy.

Run locally:  uvicorn app:app --reload
"""

from __future__ import annotations

import asyncio
import io
import json
import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from core import converter, token_utils

APP_VERSION = "2.0.0"
LOCAL_MODE = os.environ.get("TOKENCRAFT_LOCAL_MODE", "true").lower() == "true"
DEFAULT_OUTPUT_FOLDER = str(Path.home() / "TokenCraft Output")

PDF_EXTS = {"pdf"}
IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "bmp"}

app = FastAPI(title="TokenCraft by IndexCraft")

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/")
async def dashboard(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "local_mode": LOCAL_MODE,
            "default_output_folder": DEFAULT_OUTPUT_FOLDER,
            "app_version": APP_VERSION,
        },
    )


def _process_one(filename: str, data: bytes, engine, fast_mode: bool) -> dict:
    """Runs in a worker thread (see run_in_threadpool below) so the async
    event loop stays free to handle other requests while this converts."""
    ext = (Path(filename).suffix or "").lstrip(".").lower()
    content, tmp_path, error = converter.convert_bytes(filename, data, engine, fast_pdf=fast_mode)

    item = {
        "name": filename,
        "ext": ext,
        "status": "error" if error else "done",
        "content": content,
        "error": error,
        "native_tokens": None,
        "converted_tokens": None,
        "density": None,
        "fast_mode_used": bool(fast_mode and ext == "pdf"),
    }
    if error:
        return item

    item["converted_tokens"] = token_utils.estimate_text_tokens(content)

    try:
        if ext in PDF_EXTS and tmp_path:
            analysis = token_utils.analyze_pdf(tmp_path)  # single pass — see token_utils
            item["density"] = {
                "page_count": analysis.density.page_count,
                "image_count": analysis.density.image_count,
                "label": analysis.density.label,
            }
            item["native_tokens"] = analysis.image_tokens + item["converted_tokens"]

        elif ext in IMAGE_EXTS:
            has_real_text = bool(content.strip()) and not content.strip().startswith("*")
            if has_real_text:
                dims = token_utils.get_image_dimensions(io.BytesIO(data))
                if dims:
                    item["native_tokens"] = token_utils.estimate_image_tokens(*dims)
    finally:
        converter.cleanup_tmp(tmp_path)

    return item


PER_FILE_TIMEOUT_SECONDS = 90


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _summarize(results: list[dict]) -> dict:
    done = [r for r in results if r["status"] == "done"]
    comparable = [r for r in done if r["native_tokens"] is not None]

    summary = {
        "total_files": len(results),
        "converted": len(done),
        "comparable_count": len(comparable),
        # Tokens across every converted file, any format — general info only.
        "all_files_converted_tokens": sum(r["converted_tokens"] or 0 for r in done),
        # These three always come from the SAME subset (files with a real
        # native-upload baseline) so they're never mixed across bases.
        "comparable_native_tokens": None,
        "comparable_converted_tokens": None,
        "overall_multiplier": None,
        "overall_pct_saved": None,
    }
    if comparable:
        native_sum = sum(r["native_tokens"] for r in comparable)
        conv_sum = sum(r["converted_tokens"] for r in comparable)
        cmp = token_utils.compare_savings(native_sum, conv_sum)
        summary["comparable_native_tokens"] = native_sum
        summary["comparable_converted_tokens"] = conv_sum
        summary["overall_multiplier"] = cmp.multiplier
        summary["overall_pct_saved"] = cmp.pct_saved
    return summary


async def _convert_stream(files_data: list[tuple[str, bytes]], use_llm: bool, api_key: str, fast_mode: bool):
    # Built once per request, reused for every file in the batch — creating
    # a fresh MarkItDown() per file costs ~40ms of pure setup overhead each
    # time for no benefit, since conversion is sequential anyway (no
    # concurrent-access reason to keep them isolated). On a 100-file batch
    # that's several extra seconds saved for free.
    engine = converter.get_converter(use_llm, api_key)

    total = len(files_data)
    results: list[dict] = []
    yield _sse("start", {"total": total})

    # Sequential by design, not an oversight: threading and multiprocessing
    # were both benchmarked against typical office-doc/PDF batches and came
    # out *slower* than sequential conversion (Python's GIL limits real
    # thread parallelism for this CPU-bound work, and process-spawn
    # overhead outweighs the gains at normal batch sizes). See README.
    # run_in_threadpool here is only to keep the server responsive to OTHER
    # concurrent requests while one conversion runs — not to parallelize
    # this batch. Streaming progress per file is what actually helps the
    # person watching, by showing real movement instead of a frozen screen.
    for idx, (filename, data) in enumerate(files_data):
        yield _sse("file_start", {"index": idx, "total": total, "name": filename})
        try:
            item = await asyncio.wait_for(
                run_in_threadpool(_process_one, filename, data, engine, fast_mode),
                timeout=PER_FILE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            # Mainly a concern for audio/video files: markitdown transcribes
            # them via a network call to Google's speech API, which has no
            # built-in timeout. Without this, one slow/unreachable network
            # call would hang the entire batch behind it. Note: the
            # underlying thread can't actually be killed (Python threads
            # aren't cancellable) — this stops the REQUEST from hanging and
            # moves on, but the abandoned thread may keep running quietly in
            # the background until it finishes or errors out on its own.
            item = {
                "name": filename,
                "ext": (Path(filename).suffix or "").lstrip(".").lower(),
                "status": "error",
                "content": "",
                "error": f"Timed out after {PER_FILE_TIMEOUT_SECONDS}s — likely a network-dependent "
                "step (e.g. audio transcription) taking too long. Skipped so the rest of the batch could continue.",
                "native_tokens": None,
                "converted_tokens": None,
                "density": None,
                "fast_mode_used": False,
            }
        results.append(item)
        yield _sse("file_done", {"index": idx, "total": total, "item": item})

    yield _sse("complete", {"summary": _summarize(results), "local_mode": LOCAL_MODE})


@app.post("/convert")
async def convert_endpoint(
    files: list[UploadFile] = File(...),
    use_llm: bool = Form(False),
    api_key: str = Form(""),
    fast_mode: bool = Form(False),
):
    # Read every file's bytes upfront — same memory footprint as before,
    # just done before streaming starts instead of interleaved with it.
    files_data = [(f.filename, await f.read()) for f in files]
    return StreamingResponse(
        _convert_stream(files_data, use_llm, api_key, fast_mode),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _require_local_mode():
    if not LOCAL_MODE:
        raise HTTPException(
            status_code=403,
            detail="This is a hosted deployment — it has no access to your computer's "
            "filesystem. Download your files instead, or run TokenCraft locally for "
            "folder features (see the GitHub README).",
        )


@app.post("/pick-folder")
async def pick_folder():
    _require_local_mode()
    folder = await run_in_threadpool(folder_utils_pick_folder)
    return {"folder": folder}


def folder_utils_pick_folder():
    from core import folder_utils

    return folder_utils.pick_folder_dialog()


@app.post("/save-to-folder")
async def save_to_folder(payload: dict):
    _require_local_mode()
    folder = payload.get("folder")
    items = payload.get("files", [])
    if not folder:
        raise HTTPException(status_code=400, detail="No folder specified.")
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    for it in items:
        (out / (Path(it["name"]).stem + ".md")).write_text(it["content"], encoding="utf-8")
    return {"status": "ok", "count": len(items), "folder": str(out)}


@app.post("/open-folder")
async def open_folder_endpoint(payload: dict):
    _require_local_mode()
    from core import folder_utils

    folder = payload.get("folder") or DEFAULT_OUTPUT_FOLDER
    Path(folder).mkdir(parents=True, exist_ok=True)
    ok, err = await run_in_threadpool(folder_utils.open_in_explorer, folder)
    if not ok:
        raise HTTPException(status_code=500, detail=err)
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok", "version": APP_VERSION, "local_mode": LOCAL_MODE}
