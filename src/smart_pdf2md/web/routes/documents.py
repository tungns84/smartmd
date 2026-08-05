from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from smart_pdf2md.classifier import extract_pages
from smart_pdf2md.converter import MIN_NATIVE_CHARS
from smart_pdf2md.ocr.vlm.registry import list_models
from smart_pdf2md.web.deps import DbSession, require_csrf, require_owner, require_user
from smart_pdf2md.web.htmlutil import html_error, hx_redirect, shell_context, templates, wants_html
from smart_pdf2md.web.job_options import format_page_selection
from smart_pdf2md.web.models import Document, Job, User
from smart_pdf2md.web.routes.providers import _opencode_available, _paddle_available
from smart_pdf2md.web.settings import get_settings

router = APIRouter(prefix="/documents", tags=["documents"])

PDF_MAGIC = b"%PDF"
_UPLOAD_CHUNK = 1024 * 1024


def _jobs_by_document(db, owner_id: str) -> tuple[dict[str, Job], dict[str, Job]]:
    """Newest job per document, and newest one with a downloadable result."""
    jobs = db.scalars(
        select(Job).where(Job.owner_id == owner_id).order_by(Job.created_at.desc())
    ).all()
    latest: dict[str, Job] = {}
    outputs: dict[str, Job] = {}
    for job in jobs:
        latest.setdefault(job.document_id, job)
        if job.status == "succeeded" and job.output_path:
            outputs.setdefault(job.document_id, job)
    return latest, outputs


def page_metadata(doc: Document) -> list[dict]:
    """Per-page OCR flag for the picker, using the same rule as plan_ocr_pages."""
    needing = set(doc.pages_needing_ocr or [])
    native = list(doc.page_native_chars or [])
    pages = []
    for number in range(1, (doc.page_count or 0) + 1):
        index = number - 1
        thin = index < len(native) and native[index] < MIN_NATIVE_CHARS
        pages.append({"number": number, "needs_ocr": number in needing or thin})
    return pages


def _doc_json(d: Document) -> dict:
    return {
        "id": d.id,
        "original_filename": d.original_filename,
        "page_count": d.page_count,
        "pdf_type": d.pdf_type,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


def _upload_too_large(request: Request, max_mb: int):
    if wants_html(request):
        return html_error(f"Tệp vượt quá {max_mb} MB", 422)
    raise HTTPException(status_code=422, detail=f"File exceeds {max_mb}MB")


@router.get("")
async def list_documents(
    request: Request,
    db: DbSession,
    user: Annotated[User, Depends(require_user)],
):
    docs = db.scalars(
        select(Document).where(Document.owner_id == user.id).order_by(Document.created_at.desc())
    ).all()
    if wants_html(request):
        latest_jobs, latest_outputs = _jobs_by_document(db, user.id)
        return templates.TemplateResponse(
            request,
            "library.html",
            shell_context(
                request,
                db,
                user,
                documents=docs,
                latest_jobs=latest_jobs,
                latest_outputs=latest_outputs,
                max_upload_mb=get_settings().web_max_upload_mb,
            ),
        )
    return [_doc_json(d) for d in docs]


@router.post("", dependencies=[Depends(require_csrf)])
async def upload_document(
    request: Request,
    db: DbSession,
    user: Annotated[User, Depends(require_user)],
    file: UploadFile = File(...),
):
    settings = get_settings()
    max_bytes = settings.web_max_upload_mb * 1024 * 1024

    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit():
        # Multipart overhead means Content-Length can exceed file size; still a
        # useful fast reject when the whole request is clearly oversized.
        if int(content_length) > max_bytes + (1024 * 1024):
            return _upload_too_large(request, settings.web_max_upload_mb)

    doc_id = str(uuid4())
    dest_dir = Path(settings.web_data_dir) / user.id / doc_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "source.pdf"

    size_bytes = 0
    magic_ok = False
    try:
        with dest.open("wb") as out:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK)
                if not chunk:
                    break
                if size_bytes == 0:
                    magic_ok = chunk.startswith(PDF_MAGIC)
                    if not magic_ok:
                        break
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    out.close()
                    shutil.rmtree(dest_dir, ignore_errors=True)
                    return _upload_too_large(request, settings.web_max_upload_mb)
                out.write(chunk)
    except Exception:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise

    if not magic_ok or size_bytes == 0:
        shutil.rmtree(dest_dir, ignore_errors=True)
        if wants_html(request):
            return html_error("Không phải tệp PDF", 422)
        raise HTTPException(status_code=422, detail="Not a PDF (magic bytes)")

    try:
        pages, analysis = await run_in_threadpool(extract_pages, dest)
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(dest_dir, ignore_errors=True)
        if wants_html(request):
            return html_error(f"Không đọc được PDF: {exc}", 422)
        raise HTTPException(
            status_code=422, detail=f"Failed to parse PDF: {exc}"
        ) from exc

    if analysis.page_count <= 0 or not pages:
        shutil.rmtree(dest_dir, ignore_errors=True)
        if wants_html(request):
            return html_error(
                "Không đọc được trang nào từ PDF này "
                "(pdf-inspector trả về 0 và poppler cũng thất bại).",
                422,
            )
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not read any pages from this PDF "
                "(pdf-inspector returned 0 and poppler fallback failed)."
            ),
        )

    page_native_chars = [len(p.markdown.strip()) for p in pages]
    doc = Document(
        id=doc_id,
        owner_id=user.id,
        original_filename=file.filename or "upload.pdf",
        stored_path=str(dest),
        page_count=analysis.page_count,
        pdf_type=analysis.pdf_type,
        page_native_chars=page_native_chars,
        pages_needing_ocr=list(analysis.pages_needing_ocr),
        size_bytes=size_bytes,
    )
    db.add(doc)
    db.commit()

    if wants_html(request):
        return hx_redirect(request, f"/documents/{doc.id}")

    return {
        "id": doc.id,
        "page_count": doc.page_count,
        "pdf_type": doc.pdf_type,
        "original_filename": doc.original_filename,
    }


@router.get("/{document_id}")
async def get_document(
    document_id: str,
    request: Request,
    db: DbSession,
    user: Annotated[User, Depends(require_user)],
):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    require_owner(doc.owner_id, user)

    if wants_html(request):
        oc_ok, oc_reason = _opencode_available()
        pd_ok, pd_reason = _paddle_available()
        backends = [
            {
                "id": "opencode",
                "label": "OpenCode Go VLM",
                "available": oc_ok,
                "unavailable_reason": oc_reason,
            },
            {
                "id": "paddleocr",
                "label": "PaddleOCR (local)",
                "available": pd_ok,
                "unavailable_reason": pd_reason,
            },
        ]
        models = []
        for spec in list_models(enabled_only=True):
            models.append(
                {
                    "id": spec.id,
                    "label": spec.label,
                    "available": oc_ok,
                }
            )
        default_backend = "opencode" if oc_ok else ("paddleocr" if pd_ok else "opencode")
        default_model = next((m["id"] for m in models if m["available"]), models[0]["id"] if models else "")
        recent_jobs = db.scalars(
            select(Job)
            .where(Job.document_id == doc.id)
            .order_by(Job.created_at.desc())
            .limit(5)
        ).all()
        return templates.TemplateResponse(
            request,
            "document_detail.html",
            shell_context(
                request,
                db,
                user,
                doc=doc,
                page_meta=page_metadata(doc),
                backends=backends,
                models=models,
                default_backend=default_backend,
                default_model=default_model,
                recent_jobs=recent_jobs,
                format_page_selection=format_page_selection,
            ),
        )

    return {
        "id": doc.id,
        "original_filename": doc.original_filename,
        "page_count": doc.page_count,
        "pdf_type": doc.pdf_type,
        "page_native_chars": doc.page_native_chars,
        "pages_needing_ocr": doc.pages_needing_ocr,
    }


@router.get("/{document_id}/download")
async def download_source(
    document_id: str,
    db: DbSession,
    user: Annotated[User, Depends(require_user)],
):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    require_owner(doc.owner_id, user)
    return FileResponse(doc.stored_path, filename=doc.original_filename)


@router.delete("/{document_id}", dependencies=[Depends(require_csrf)])
async def delete_document(
    document_id: str,
    db: DbSession,
    user: Annotated[User, Depends(require_user)],
):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    require_owner(doc.owner_id, user)
    path = Path(doc.stored_path).parent
    db.delete(doc)
    db.commit()
    shutil.rmtree(path, ignore_errors=True)
    return {"ok": True}
