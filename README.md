# Smart PDF to Markdown (`pdf2md-smart`)

Chuyển đổi PDF sang Markdown chất lượng cao, **100% local** — kết hợp **pdf-inspector** (phân loại + trích xuất native cực nhanh) và **Surya 2** (OCR local cho trang scanned). Hệ thống tự quyết định trang nào dùng native, trang nào cần OCR, rồi merge thành một file Markdown duy nhất có page marker.

## Tính năng

- Phân loại PDF: `text_based` / `scanned` / `image_based` / `mixed` (~10-50ms)
- Chỉ OCR trang thực sự cần — text-based PDF xử lý < 300ms/trang
- OCR tiếng Việt + tiếng Anh chất lượng cao (Surya 2), giữ heading/bold/table
- Merge theo thứ tự trang với `<!-- Page N -->`
- CLI + Python API, chạy hoàn toàn offline
- Tùy chọn DPI, ngôn ngữ, compact, chọn trang

## Cài đặt

Xem chi tiết: **[docs/INSTALL.md](docs/INSTALL.md)** (poppler + llama.cpp + model GGUF).

```bash
uv sync --group dev
```

## Sử dụng CLI

```bash
# Convert đơn giản
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
      └── trang cần OCR → pdf2image → Surya 2 → markdown
                                        Merge Engine (<!-- Page N -->) → .md
```

Chi tiết: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**

## Test

```bash
uv run pytest
```

## Lộ trình

- [x] Phase 1 (MVP): classify → native extract → OCR → merge, CLI + API, tiếng Việt/Anh, page marker
- [ ] Phase 2: progress đẹp hơn, post-processing OCR, `--compact` chi tiết
- [ ] Phase 3: batch song song, Docker, backend OCR có thể chọn (PaddleOCR fallback)

## License

MIT (code). Surya weights dùng license OpenRAIL-M — xem [docs/INSTALL.md](docs/INSTALL.md#6-license).
