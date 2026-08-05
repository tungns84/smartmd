"""Per-page OCR markdown cache keyed by PDF content hash + options fingerprint."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from smart_pdf2md.config import Options
from smart_pdf2md.ocr.vlm.prompts import ocr_prompt

_HASH_CHUNK = 1024 * 1024


def get_cache_root() -> Path:
    """Return cache root: ``PDF2MD_CACHE_DIR`` or platform default."""
    override = os.environ.get("PDF2MD_CACHE_DIR", "").strip()
    if override:
        return Path(override)
    local_app = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app:
        return Path(local_app) / "smart-pdf2md" / "cache"
    return Path.home() / ".cache" / "smart-pdf2md"


def file_sha256(path: str | Path) -> str:
    """Stream SHA-256 of file contents."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def options_fingerprint(options: Options) -> str:
    """Stable fingerprint string for OCR-relevant options."""
    langs = ",".join(sorted(options.languages))
    fingerprint = (
        f"dpi={options.dpi}"
        f"|backend={options.ocr_backend}"
        f"|model={options.vlm_model}"
        f"|jq={options.vlm_jpeg_quality}"
        f"|lang={langs}"
    )
    if options.ocr_backend == "opencode":
        # VLM output depends on the prompt wording, so editing the prompt has to
        # expire pages transcribed under the previous one.
        fingerprint += f"|prompt={fingerprint_hash8(ocr_prompt())}"
    return fingerprint


def fingerprint_hash8(fingerprint: str) -> str:
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:8]


def cache_dir(pdf_hash: str, fingerprint: str, *, root: Optional[Path] = None) -> Path:
    """``{cache_root}/{pdf_hash16}_{fp8}/``."""
    base = root if root is not None else get_cache_root()
    return base / f"{pdf_hash[:16]}_{fingerprint_hash8(fingerprint)}"


class OcrPageCache:
    """Load/save per-page OCR markdown under a fingerprint-scoped cache dir."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.pages_dir = root / "pages"

    @classmethod
    def for_pdf(
        cls,
        pdf_path: str | Path,
        options: Options,
        *,
        cache_root: Optional[Path] = None,
    ) -> "OcrPageCache":
        pdf_path = Path(pdf_path)
        pdf_hash = file_sha256(pdf_path)
        fp = options_fingerprint(options)
        directory = cache_dir(pdf_hash, fp, root=cache_root)
        cache = cls(directory)
        cache.ensure_meta(pdf_path, pdf_hash=pdf_hash, fingerprint=fp)
        return cache

    def ensure_meta(
        self,
        pdf_path: str | Path,
        *,
        pdf_hash: str,
        fingerprint: str,
    ) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        meta_path = self.root / "meta.json"
        pdf_path = Path(pdf_path)
        try:
            st = pdf_path.stat()
            size = st.st_size
            mtime = st.st_mtime
        except OSError:
            size = None
            mtime = None
        meta = {
            "pdf_path": str(pdf_path.resolve()) if pdf_path.exists() else str(pdf_path),
            "pdf_hash": pdf_hash,
            "size": size,
            "mtime": mtime,
            "fingerprint": fingerprint,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if meta_path.exists():
            try:
                existing = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(existing, dict) and "created_at" in existing:
                    meta["created_at"] = existing["created_at"]
            except (OSError, json.JSONDecodeError):
                pass
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=".meta-",
            suffix=".json.tmp",
            dir=self.root,
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                json.dump(meta, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            Path(tmp_name).replace(meta_path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def _page_path(self, page: int) -> Path:
        return self.pages_dir / f"{page:04d}.md"

    def load(self, page: int) -> Optional[str]:
        path = self._page_path(page)
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8")
        # Heal polluted empty-page cache: treat blank as a miss so OCR retries.
        if not text.strip():
            return None
        return text

    def save(self, page: int, markdown: str) -> None:
        if not (markdown or "").strip():
            return
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        target = self._page_path(page)
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=f".page-{page:04d}-",
            suffix=".md.tmp",
            dir=self.pages_dir,
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(markdown)
            Path(tmp_name).replace(target)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def cached_pages(self) -> set[int]:
        if not self.pages_dir.is_dir():
            return set()
        pages: set[int] = set()
        for path in self.pages_dir.glob("*.md"):
            if path.name.startswith("."):
                continue
            stem = path.stem
            if len(stem) == 4 and stem.isdigit():
                pages.add(int(stem))
        return pages
