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
   cache.py ── hit? → load pages/NNNN.md (source=cache)
         │ miss / --force-ocr / --no-cache
         ▼
   render.py ── pdf2image (poppler, DPI config)
         │       render theo nhóm trang liên tiếp (tối ưu spawn)
         ▼
   ocr/opencode_backend.py ── OpenCode Go VLM (mặc định)
         │       PIL → JPEG q=85 → base64
         │       POST /zen/go/v1/messages (x-api-key, model qwen3.6-plus)
         │       fallback grok-4.5 /chat/completions nếu model từ chối ảnh
         │       strip code fence + NFC normalize
         │       → atomic save cache ngay sau mỗi trang
         │
         │  (hoặc ocr/paddleocr_backend.py khi --ocr-backend paddleocr)
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
| `ocr/base.py` | `OcrBackend` ABC + registry `get_ocr_backend(name)` (`opencode` \| `paddleocr`) |
| `ocr/opencode_backend.py` | OCR cloud VLM: Anthropic Messages + retry; prompt Markdown; NFC postprocess |
| `ocr/paddleocr_backend.py` | OCR local PaddleOCR: lazy-init engine, predict per-page, reading-order markdown |
| `merge.py` | `merge_pages()`: bỏ trang rỗng, thêm page marker, compact |
| `cache.py` | Cache OCR theo trang: `sha256(PDF)` + fingerprint options → `{hash16}_{fp8}/pages/NNNN.md` |
| `converter.py` | Orchestration: `convert()` → str, `convert_full()` → `ConversionResult`; `plan_ocr_pages()` pure routing; emits `ConversionEvent` via listener |
| `events.py` | UI-agnostic listener port (`ConversionListener`) + event dataclasses |
| `progress.py` | `RichConversionListener` + OCR progress bar helpers |
| `ocr/vlm/` | Model registry, TOML overlay, dialects (Anthropic/OpenAI), image limits, postprocess |
| `web/` | Optional FastAPI surface (auth, documents, jobs/SSE, credits) — never imported by CLI core |
| `cli.py` | Typer CLI `pdf2md-smart` |

## Quyết định thiết kế

1. **Per-page markdown từ pdf-inspector** (`extract_pages_markdown`) thay vì 1 markdown toàn file → merge theo trang chính xác, không cần fallback phức tạp (PRD §15.2 đã được API hiện tại giải quyết).
2. **OCR chỉ trang cần thiết**: `pages_needing_ocr` (1-indexed) ∩ trang được chọn. `--force-ocr` để ép khi text layer bị hỏng encoding mà classifier không phát hiện.
3. **OcrBackend ABC từ MVP**: cho phép thêm/đổi backend mà không đổi converter. Mặc định `opencode` vì PaddleOCR mất dấu tiếng Việt (charset).
4. **OpenCode Go Anthropic format**: Qwen models dùng `/zen/go/v1/messages` với header `x-api-key` (probe: Bearer-only → 401).
5. **API key chỉ qua env** `OPENCODE_API_KEY` — không đưa key vào CLI args / log.
6. **OCR sequential per-page**: dễ map page ↔ kết quả và xử lý lỗi từng trang.
7. **Trang đánh số 1-indexed** ở `<!-- Page N -->` và API OCR; nội bộ `PageResult.page` 0-indexed.
8. **paddlepaddle không pin trong deps chính** — wheel CPU/GPU khác nhau; INSTALL hướng dẫn cài khi dùng offline.
9. **Cache OCR theo hash nội dung PDF** (không path/mtime): khóa `{pdf_hash16}_{fp8}` với fingerprint `dpi|backend|model|jq|lang`. Ghi atomic từng trang ngay sau OCR → chạy lại cùng lệnh = resume. `--no-cache` tắt đọc/ghi; `--force-ocr` bỏ qua hit nhưng vẫn ghi đè cache. Không cache trang native.

## Xử lý lỗi

| Tình huống | Xử lý |
|---|---|
| PDF hỏng/encrypted/không đọc được | `PdfReadError` (wrap exception của pdf-inspector) |
| Thiếu `OPENCODE_API_KEY` | `OcrBackendError` hướng dẫn https://opencode.ai/auth |
| HTTP 401 / 429 từ OpenCode | `OcrBackendError` rõ (key sai / hết usage) |
| Timeout / 5xx | Retry 2 lần (backoff 2s → 4s) rồi raise |
| Thiếu `paddleocr` / `paddlepaddle` | `OcrBackendError` hướng dẫn `docs/INSTALL.md` |
| Lỗi init / predict runtime (Paddle) | `OcrBackendError` kèm thông báo |
| Không có trang khớp `--page` | `ValueError` rõ ràng |
| Thiếu poppler | `PdfReadError` từ pdf2image kèm gợi ý `PDF2MD_POPPLER_DIR` |

## Hạn chế đã biết

- **PaddleOCR mất dấu tiếng Việt**: charset recognition không có Vietnamese Extended (U+1EA0–U+1EF9) — bug upstream; dùng `opencode` (mặc định) khi cần dấu đầy đủ.
- **VLM phụ thuộc mạng + usage limit**: cần `OPENCODE_API_KEY` và subscription Go; hết limit → 429 (bật Use balance hoặc đợi reset).
- **Heuristic trang native quá ngắn**: trong doc dạng mixed/scanned/image_based, trang native có < 120 ký tự bị coi là cần OCR — bắt được case "page có text layer chữ ký đè lên ảnh scan". Có thể đánh lừa với trang gần như trống thật.
- **Phát hiện encoding hỏng không hoàn hảo**: một số PDF có text layer "garbage" nhưng không được đánh dấu cần OCR → dùng `--force-ocr`.
- **PaddleOCR không trả HTML markup** (heading/bold/table): join line theo reading-order bbox + paragraph gap; VLM thường trả heading/bảng tốt hơn.
