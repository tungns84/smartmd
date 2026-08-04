# Kiến trúc

## Luồng xử lý

```
PDF Input
   │
   ▼
classifier.py  ── pdf_inspector.extract_pages_markdown()
   │              → pdf_type, confidence, page_count,
   │                per-page markdown (native) + needs_ocr flag
   │                + has_encoding_issues, pages_needing_ocr
   │
   ├── Trang native OK ───────────────────────┐
   │                                          │
   └── Trang cần OCR (pages_needing_ocr ∩ selected)
         │
         ▼
   render.py ── pdf2image (poppler, DPI config)
         │       render theo nhóm trang liên tiếp (tối ưu spawn)
         ▼
   ocr/surya_backend.py ── Surya 2 (llama.cpp / vllm)
         │       full-page OCR → HTML blocks → html_to_markdown()
         │       callback progress: "✓ Page N (x ký tự)"
         ▼
converter.py ── merge.py: ghép theo thứ tự trang
   │           <!-- Page N -->, compact mode
   ▼
Markdown Output (file / stdout)
```

## Module map

| Module | Trách nhiệm |
|---|---|
| `classifier.py` | Wrapper pdf-inspector: `analyze_pdf()`, `extract_pages()` → `AnalysisResult`, `PageResult` (0-indexed) |
| `render.py` | Render PDF→PIL image qua pdf2image; dò poppler (`PDF2MD_POPPLER_DIR` → `tools/poppler/`) |
| `ocr/base.py` | `OcrBackend` ABC + registry `get_ocr_backend(name)` |
| `ocr/surya_backend.py` | OCR qua Surya 2: dò llama-server (`LLAMA_CPP_BINARY` → `tools/llama.cpp/` → PATH → `SURYA_INFERENCE_URL`), OCR theo chunk ≤ 8 trang, `html_to_markdown()` |
| `merge.py` | `merge_pages()`: bỏ trang rỗng, thêm page marker, compact |
| `converter.py` | Orchestration: `convert()` → str, `convert_full()` → `ConversionResult`; lọc trang (`pages`), ép OCR (`force_ocr`) |
| `progress.py` | Callback hiển thị tiến trình per-page |
| `cli.py` | Typer CLI `pdf2md-smart` |

## Quyết định thiết kế

1. **Per-page markdown từ pdf-inspector** (`extract_pages_markdown`) thay vì 1 markdown toàn file → merge theo trang chính xác, không cần fallback phức tạp (PRD §15.2 đã được API hiện tại giải quyết).
2. **OCR chỉ trang cần thiết**: `pages_needing_ocr` (1-indexed) ∩ trang được chọn. `--force-ocr` để ép khi text layer bị hỏng encoding mà classifier không phát hiện.
3. **OcrBackend ABC từ MVP**: cho phép thêm backend (PaddleOCR...) mà không đổi converter.
4. **Streaming theo chunk (≤8 trang)**: giới hạn RAM khi file scanned dài (839 trang) — render + OCR từng lô rồi gom kết quả.
5. **Trang đánh số 1-indexed** ở `<!-- Page N -->` và API OCR; nội bộ `PageResult.page` 0-indexed, khớp với pdf-inspector.
6. **Surya 2 qua llama-server riêng** (`SURYA_INFERENCE_URL`) khi xử lý nhiều file — tránh load model lại mỗi lần (mỗi lần ~30-60s).

## Xử lý lỗi

| Tình huống | Xử lý |
|---|---|
| PDF hỏng/encrypted/không đọc được | `PdfReadError` (wrap exception của pdf-inspector) |
| Không có llama-server | `OcrBackendError` kèm hướng dẫn INSTALL.md |
| Server OCR chết giữa chừng | `OcrBackendError` |
| Không cài surya-ocr | `OcrBackendError` hướng dẫn `uv add surya-ocr` |
| Không có trang khớp `--page` | `ValueError` rõ ràng |
| Thiếu poppler | `PdfReadError` từ pdf2image kèm gợi ý `PDF2MD_POPPLER_DIR` |

## Hạn chế đã biết

- **OCR CPU chậm**: ~280-365s/trang trên máy không GPU (đo thực tế, llama.cpp). Text-based PDF không bị ảnh hưởng.
- **Heuristic trang native quá ngắn**: trong doc dạng mixed/scanned/image_based, trang native có < 120 ký tự bị coi là cần OCR — bắt được case "page có text layer chữ ký đè lên ảnh scan" (vd: page 1 Thông-tư chỉ có dòng "Ký bởi:" nhưng letterhead là ảnh). Có thể đánh lừa với trang gần như trống thật.
- **Phát hiện encoding hỏng không hoàn hảo**: một số PDF có text layer "garbage" (font CID không có ToUnicode) nhưng không được đánh dấu cần OCR → dùng `--force-ocr`.
- **Model tải 1 lần từ HuggingFace** (~1.4GB) trước khi offline hoàn toàn.
