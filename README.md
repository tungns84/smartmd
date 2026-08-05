# Smart PDF to Markdown (`pdf2md-smart`)

Chuyển đổi PDF sang Markdown chất lượng cao — kết hợp **pdf-inspector** (phân loại + trích xuất native cực nhanh) và **OpenCode Go VLM** (OCR mặc định, giữ đủ dấu tiếng Việt). **PaddleOCR** vẫn có sẵn cho chế độ offline (`--ocr-backend paddleocr`). Hệ thống tự quyết định trang nào dùng native, trang nào cần OCR, rồi merge thành một file Markdown duy nhất có page marker.

## Tính năng

- Phân loại PDF: `text_based` / `scanned` / `image_based` / `mixed` (~10-50ms)
- Chỉ OCR trang thực sự cần — text-based PDF xử lý < 300ms/trang
- OCR mặc định qua OpenCode Go VLM (`qwen3.6-plus`) — Markdown có cấu trúc, dấu tiếng Việt đầy đủ (cần mạng + API key)
- OCR offline tùy chọn: PaddleOCR 3.x (`--ocr-backend paddleocr`)
- Cache OCR theo hash PDF — chạy lại cùng lệnh để resume; `--no-cache` để tắt
- Merge theo thứ tự trang với `<!-- Page N -->`
- CLI + Python API
- Tùy chọn DPI, ngôn ngữ, compact, chọn trang, model VLM

## Cài đặt

Xem chi tiết: **[docs/INSTALL.md](docs/INSTALL.md)** (OpenCode API key + poppler; PaddleOCR nếu dùng offline).

Web app (login, document library, jobs/SSE, credits): **[docs/WEB.md](docs/WEB.md)** — `uv sync --extra web`.

Testing tiers + coverage ratchet: **[docs/TESTING.md](docs/TESTING.md)**.

```bash
# 1) project deps
uv sync --group dev

# 2) API key + model OpenCode Go (OCR mặc định)
cp .env.example .env   # điền OPENCODE_API_KEY=... (https://opencode.ai/auth)
# Hoặc: export OPENCODE_API_KEY=...  /  $env:OPENCODE_API_KEY="..."
```

Poppler vẫn cần để render trang PDF → ảnh trước khi gọi VLM / PaddleOCR.

## Sử dụng CLI

```bash
# Convert đơn giản (OCR mặc định = opencode)
pdf2md-smart tai-lieu.pdf

# Chỉ định output
pdf2md-smart tai-lieu.pdf -o ket-qua.md

# Ngôn ngữ + DPI
pdf2md-smart tai-lieu.pdf -o ket-qua.md --lang vi,en --dpi 200

# Chỉ phân loại, không convert
pdf2md-smart tai-lieu.pdf --analyze

# Xử lý một số trang
pdf2md-smart tai-lieu.pdf --page 1-5,8

# Ép OCR toàn bộ (khi text layer bị hỏng dấu tiếng Việt)
pdf2md-smart tai-lieu.pdf -o ket-qua.md --force-ocr

# Resume: chạy lại cùng lệnh — trang OCR đã cache được bỏ qua
# (Ctrl+C giữa chừng rồi chạy lại là được; tắt bằng --no-cache)
pdf2md-smart tai-lieu.pdf -o ket-qua.md

# Tắt cache OCR
pdf2md-smart tai-lieu.pdf -o ket-qua.md --no-cache

# Offline OCR (PaddleOCR)
pdf2md-smart tai-lieu.pdf -o ket-qua.md --ocr-backend paddleocr

# Đổi model VLM
pdf2md-smart tai-lieu.pdf -o ket-qua.md --vlm-model qwen3.6-plus

# Chế độ im lặng
pdf2md-smart tai-lieu.pdf -o ket-qua.md --quiet
```

## Python API

```python
from smart_pdf2md import convert, analyze

markdown = convert("tai-lieu.pdf", output="ket-qua.md", dpi=200)
print(markdown[:500])

info = analyze("tai-lieu.pdf")
print(info.pdf_type, info.confidence, info.pages_needing_ocr)
```

API đầy đủ: `convert()`, `convert_full()` (trả metadata), `analyze()`, `Options`, `ConversionResult`, `PageResult`.

## Kiến trúc

```
PDF → pdf-inspector (classify + native per-page markdown)
      ├── trang native OK ───────────────┐
      └── trang cần OCR → cache hit? ────┤
                    miss → pdf2image → OpenCode Go VLM (qwen3.6-plus)
                                        │  (hoặc PaddleOCR offline)
                                        │  → save cache per page
                                        Merge Engine (<!-- Page N -->) → .md
```

Chi tiết: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**

## Test

```bash
uv run pytest
```

E2E OCR offline (cần paddlepaddle + model): `PDF2MD_OCR_E2E=1 uv run pytest tests/test_e2e_ocr.py`

## Lộ trình

- [x] Phase 1 (MVP): classify → native extract → OCR → merge, CLI + API, tiếng Việt/Anh, page marker
- [x] OpenCode Go VLM backend (mặc định) — sửa mất dấu tiếng Việt của PaddleOCR charset
- [ ] Phase 2: progress đẹp hơn, post-processing OCR, `--compact` chi tiết
- [ ] Phase 3: batch song song, Docker, tối ưu GPU PaddleOCR

## License

MIT (code). OCR mặc định dùng OpenCode Go (cần subscription/key). PaddleOCR / PaddlePaddle (Apache-2.0) cho offline.
