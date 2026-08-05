from pathlib import Path

import pytest

from smart_pdf2md import cache as cache_mod
from smart_pdf2md.cache import (
    OcrPageCache,
    cache_dir,
    file_sha256,
    fingerprint_hash8,
    get_cache_root,
    options_fingerprint,
)
from smart_pdf2md.config import Options
from smart_pdf2md.models import PageResult
from smart_pdf2md.ocr.base import OcrBackend


def test_file_sha256_stable(tmp_path: Path):
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF-1.4 hello cache")
    assert file_sha256(path) == file_sha256(path)
    assert len(file_sha256(path)) == 64


def test_options_fingerprint_changes_with_dpi():
    a = Options(dpi=200, ocr_backend="opencode", vlm_model="qwen3.6-plus")
    b = Options(dpi=150, ocr_backend="opencode", vlm_model="qwen3.6-plus")
    assert options_fingerprint(a) != options_fingerprint(b)


def test_options_fingerprint_changes_with_ocr_prompt(monkeypatch):
    opts = Options(ocr_backend="opencode", vlm_model="qwen3.6-plus")
    before = options_fingerprint(opts)
    monkeypatch.setattr(cache_mod, "ocr_prompt", lambda profile="default": "reworded")
    assert options_fingerprint(opts) != before


def test_options_fingerprint_ignores_prompt_for_paddleocr(monkeypatch):
    opts = Options(ocr_backend="paddleocr")
    before = options_fingerprint(opts)
    monkeypatch.setattr(cache_mod, "ocr_prompt", lambda profile="default": "reworded")
    assert options_fingerprint(opts) == before


def test_cache_dir_uses_hash16_and_fp8(tmp_path: Path):
    fp = "dpi=200|backend=opencode|model=x|jq=85|lang=en,vi"
    path = cache_dir("abcdef0123456789ffff", fp, root=tmp_path)
    assert path.parent == tmp_path
    assert path.name == f"abcdef0123456789_{fingerprint_hash8(fp)}"


def test_save_load_roundtrip(tmp_path: Path):
    cache = OcrPageCache(tmp_path / "c")
    cache.ensure_meta(
        tmp_path / "a.pdf",
        pdf_hash="abc",
        fingerprint="dpi=200|backend=opencode|model=m|jq=85|lang=en",
    )
    cache.save(3, "# Hello\n\nworld")
    assert cache.load(3) == "# Hello\n\nworld"
    assert cache.load(1) is None
    assert cache.cached_pages() == {3}


def test_load_treats_blank_as_miss(tmp_path: Path):
    cache = OcrPageCache(tmp_path / "c")
    cache.pages_dir.mkdir(parents=True)
    blank = cache.pages_dir / "0002.md"
    blank.write_text("   \n\n", encoding="utf-8")
    assert cache.load(2) is None
    cache.save(2, "")
    assert blank.read_text(encoding="utf-8") == "   \n\n"  # save refused
    cache.save(2, "real content")
    assert cache.load(2) == "real content"


def test_save_atomic_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cache = OcrPageCache(tmp_path / "c")
    cache.pages_dir.mkdir(parents=True)
    cache.save(1, "first")

    real_replace = Path.replace
    calls: list[tuple[Path, Path]] = []

    def tracking_replace(self: Path, target: Path):
        calls.append((self, target))
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", tracking_replace)
    cache.save(1, "second")
    assert cache.load(1) == "second"
    assert len(calls) == 1
    assert calls[0][1] == cache.pages_dir / "0001.md"
    assert calls[0][0].suffix == ".tmp" or ".tmp" in calls[0][0].name


def test_different_fingerprint_different_path(tmp_path: Path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-cache-fp")
    opts_a = Options(dpi=200, use_cache=True)
    opts_b = Options(dpi=150, use_cache=True)
    monkey_root = tmp_path / "root"
    ca = OcrPageCache.for_pdf(pdf, opts_a, cache_root=monkey_root)
    cb = OcrPageCache.for_pdf(pdf, opts_b, cache_root=monkey_root)
    assert ca.root != cb.root
    ca.save(1, "A")
    assert cb.load(1) is None


def test_get_cache_root_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("PDF2MD_CACHE_DIR", str(tmp_path / "custom"))
    assert get_cache_root() == tmp_path / "custom"


def _fake_extract_two_ocr_pages(monkeypatch, converter_mod):
    from smart_pdf2md.classifier import AnalysisResult

    analysis = AnalysisResult(
        pdf_type="scanned",
        confidence=0.9,
        page_count=2,
        pages_needing_ocr=[1, 2],
        has_encoding_issues=False,
        is_complex_layout=False,
        title=None,
        processing_time_ms=1,
        recommendation="",
    )

    def fake_extract(_path):
        pages = [
            PageResult(page=0, markdown="", needs_ocr=True),
            PageResult(page=1, markdown="", needs_ocr=True),
        ]
        return pages, analysis

    monkeypatch.setattr(converter_mod, "extract_pages", fake_extract)


def test_convert_full_cache_resume(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from smart_pdf2md import converter as conv

    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-resume-test")
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("PDF2MD_CACHE_DIR", str(cache_root))

    calls: list[list[int]] = []

    class _CountingBackend(OcrBackend):
        name = "fake"

        def ocr_pages(self, pages, pdf_path, options, on_page_done=None, on_page_start=None):
            page_nums = [p.page + 1 for p in pages]
            calls.append(page_nums)
            out = {}
            for p in pages:
                n = p.page + 1
                md = f"OCR page {n}"
                out[n] = md
                if on_page_done is not None:
                    on_page_done(n, len(md), md)
            return out

    _fake_extract_two_ocr_pages(monkeypatch, conv)
    monkeypatch.setattr(conv, "get_ocr_backend", lambda name: _CountingBackend())

    first = conv.convert_full(pdf, show_progress=False, use_cache=True)
    assert calls == [[1, 2]]
    assert first.cache_hits == 0
    assert first.cache_misses == 2
    assert first.pages[0].source == "ocr"
    assert "OCR page 1" in first.markdown

    second = conv.convert_full(pdf, show_progress=False, use_cache=True)
    assert calls == [[1, 2]]  # no second OCR call
    assert second.cache_hits == 2
    assert second.cache_misses == 0
    assert second.pages[0].source == "cache"
    assert second.pages[1].source == "cache"
    assert second.markdown == first.markdown


def test_convert_full_no_cache_always_ocr(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from smart_pdf2md import converter as conv

    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-nocache-test")
    monkeypatch.setenv("PDF2MD_CACHE_DIR", str(tmp_path / "cache"))

    calls: list[int] = []

    class _CountingBackend(OcrBackend):
        name = "fake"

        def ocr_pages(self, pages, pdf_path, options, on_page_done=None, on_page_start=None):
            calls.append(len(pages))
            out = {}
            for p in pages:
                n = p.page + 1
                md = f"OCR {n}"
                out[n] = md
                if on_page_done is not None:
                    on_page_done(n, len(md), md)
            return out

    _fake_extract_two_ocr_pages(monkeypatch, conv)
    monkeypatch.setattr(conv, "get_ocr_backend", lambda name: _CountingBackend())

    conv.convert_full(pdf, show_progress=False, use_cache=False)
    conv.convert_full(pdf, show_progress=False, use_cache=False)
    assert calls == [2, 2]


def test_force_ocr_overwrites_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from smart_pdf2md import converter as conv

    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-force-cache")
    monkeypatch.setenv("PDF2MD_CACHE_DIR", str(tmp_path / "cache"))

    version = {"n": 0}

    class _VersionedBackend(OcrBackend):
        name = "fake"

        def ocr_pages(self, pages, pdf_path, options, on_page_done=None, on_page_start=None):
            version["n"] += 1
            tag = version["n"]
            out = {}
            for p in pages:
                n = p.page + 1
                md = f"v{tag}-page{n}"
                out[n] = md
                if on_page_done is not None:
                    on_page_done(n, len(md), md)
            return out

    _fake_extract_two_ocr_pages(monkeypatch, conv)
    monkeypatch.setattr(conv, "get_ocr_backend", lambda name: _VersionedBackend())

    r1 = conv.convert_full(pdf, show_progress=False, use_cache=True)
    assert "v1-page1" in r1.markdown

    r2 = conv.convert_full(pdf, show_progress=False, use_cache=True, force_ocr=True)
    assert r2.cache_hits == 0
    assert r2.cache_misses == 2
    assert "v2-page1" in r2.markdown

    r3 = conv.convert_full(pdf, show_progress=False, use_cache=True)
    assert r3.cache_hits == 2
    assert "v2-page1" in r3.markdown
