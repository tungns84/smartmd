from __future__ import annotations

import os
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from smart_pdf2md.cache import OcrPageCache
from smart_pdf2md.config import Options
from smart_pdf2md.converter import plan_ocr_pages
from smart_pdf2md.ocr.vlm.registry import list_models, registry_fingerprint
from smart_pdf2md.web.deps import DbSession, require_admin, require_user
from smart_pdf2md.web.eta import seconds_per_page_prior
from smart_pdf2md.web.job_options import estimate_job_cost_usd, parse_page_selection
from smart_pdf2md.web.models import Document, Job, User

router = APIRouter(tags=["providers"])


def _paddle_available() -> tuple[bool, Optional[str]]:
    try:
        import paddle  # noqa: F401
        from paddleocr import PaddleOCR  # noqa: F401

        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, f"paddleocr unavailable: {exc}"


def _opencode_available() -> tuple[bool, Optional[str]]:
    key = (os.environ.get("OPENCODE_API_KEY") or "").strip()
    if not key:
        return False, "OPENCODE_API_KEY not set"
    return True, None


@router.get("/api/providers")
async def api_providers(user: Annotated[User, Depends(require_user)]):
    oc_ok, oc_reason = _opencode_available()
    pd_ok, pd_reason = _paddle_available()
    models = []
    for spec in list_models(enabled_only=True):
        available = oc_ok
        reason = None if oc_ok else oc_reason
        models.append(
            {
                "id": spec.id,
                "label": spec.label,
                "provider": "opencode",
                "enabled": True,
                "available": available,
                "unavailable_reason": reason if not available else None,
                "dialect": spec.capability.dialect,
                "fallback_model": spec.capability.fallback_model,
                "max_output_tokens": spec.capability.max_output_tokens,
            }
        )
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
    return {
        "backends": backends,
        "models": models,
        "registry_fingerprint": registry_fingerprint(),
        "credits": user.credits,
    }


@router.get("/api/documents/{document_id}/cost-estimate")
def cost_estimate(
    document_id: str,
    db: DbSession,
    user: Annotated[User, Depends(require_user)],
    backend: str = "opencode",
    model: Optional[str] = None,
    force_ocr: bool = False,
    use_cache: bool = True,
    dpi: int = 200,
    pages: Optional[str] = None,
):
    doc = db.get(Document, document_id)
    if doc is None or doc.owner_id != user.id:
        return {"error": "not found"}
    try:
        selected_pages = parse_page_selection(pages, doc.page_count)
    except HTTPException as exc:
        return {"error": str(exc.detail)}
    ocr_pages = plan_ocr_pages(
        pdf_type=doc.pdf_type or "scanned",
        page_count=doc.page_count,
        pages_needing_ocr=list(doc.pages_needing_ocr or []),
        page_native_chars=list(doc.page_native_chars or []),
        force_ocr=force_ocr,
        selected_pages=selected_pages,
    )
    cached = 0
    if use_cache and backend == "opencode":
        opts = Options(
            ocr_backend=backend,
            vlm_model=model or "qwen3.6-plus",
            dpi=dpi,
            use_cache=True,
        )
        try:
            cache = OcrPageCache.for_pdf(doc.stored_path, opts)
            cached = len(set(cache.cached_pages()) & set(ocr_pages))
        except Exception:  # noqa: BLE001
            cached = 0
    hold = max(0, len(ocr_pages) - cached)

    # Dynamic average from user's past jobs when available
    past = db.scalars(
        select(Job).where(
            Job.owner_id == user.id,
            Job.status == "succeeded",
            Job.ocr_input_tokens > 0,
        )
    ).all()
    if past:
        avg_in = int(sum(j.ocr_input_tokens for j in past) / len(past))
        avg_out = int(sum(j.ocr_output_tokens for j in past) / len(past))
        # normalize to per-page roughly
        avg_pages = max(1, sum(1 for _ in past))
        avg_in = max(500, avg_in // avg_pages)
        avg_out = max(200, avg_out // avg_pages)
    else:
        avg_in, avg_out = 3000, 1200

    usd = estimate_job_cost_usd(
        model=model,
        ocr_pages=hold,
        avg_input_tokens=avg_in,
        avg_output_tokens=avg_out,
    )
    seconds_per_page, eta_basis = seconds_per_page_prior(
        db, user_id=user.id, backend=backend, model=model
    )
    return {
        "ocr_pages": len(ocr_pages),
        "cached_pages": cached,
        "credits_needed": hold,
        "credits_balance": user.credits,
        "estimated_usd": usd,
        "used_history": bool(past),
        "estimated_seconds": int(round(hold * seconds_per_page)),
        "eta_basis": eta_basis,
    }


@router.get("/admin/providers")
async def admin_providers(admin: Annotated[User, Depends(require_admin)]):
    return {
        "registry_fingerprint": registry_fingerprint(),
        "models": [
            {
                "id": s.id,
                "label": s.label,
                "source": "builtin",
                "enabled": s.enabled,
                "dialect": s.capability.dialect,
            }
            for s in list_models()
        ],
    }
