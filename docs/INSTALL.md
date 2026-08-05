# Hướng dẫn cài đặt

`pdf2md-smart` cần: Python env, poppler (render PDF→ảnh), và **OpenCode Go API key** cho OCR mặc định. **PaddleOCR** là tùy chọn offline.

## 1. Python environment

Yêu cầu: Python 3.10+ (khuyến nghị 3.12), [uv](https://docs.astral.sh/uv/).

```bash
uv sync --group dev

# Web app (FastAPI + Postgres + Redis) — optional
uv sync --extra web --group dev
```

`uv sync` cài `pdf-inspector`, `pdf2image`, `requests`, `paddleocr`, `typer`, `rich` (và deps của chúng). Web extras: xem [WEB.md](WEB.md).

## 2. OpenCode Go (OCR mặc định)

Backend mặc định `opencode` gọi VLM qua OpenCode Go (`qwen3.6-plus`, Anthropic Messages tại `/zen/go/v1/messages`).

1. Đăng ký / lấy key tại [opencode.ai/auth](https://opencode.ai/auth)
2. Subscribe **OpenCode Go** (allowance ~$60/tháng cho hầu hết model open)
3. Cấu hình key (và tùy chọn model) qua `.env` — không có CLI flag cho API key:

```bash
cp .env.example .env
# Điền OPENCODE_API_KEY=sk-...
# Tùy chọn: OPENCODE_VLM_MODEL=qwen3.6-plus
```

Hoặc export biến môi trường OS (dotenv **không** ghi đè biến đã set sẵn):

```bash
export OPENCODE_API_KEY=sk-...
# Windows PowerShell:
# $env:OPENCODE_API_KEY="sk-..."
```

Biến hỗ trợ: `OPENCODE_API_KEY` (bắt buộc), `OPENCODE_VLM_MODEL` (mặc định `qwen3.6-plus`), `OPENCODE_BASE_URL` (mặc định `https://opencode.ai/zen/go/v1`). CLI `--vlm-model` ghi đè model từ `.env`/env.

### Chi phí ước lượng

| Hạng mục | Giá trị |
|---|---|
| Model mặc định | `qwen3.6-plus` |
| ~$/trang | ~$0,0055 |
| Allowance Go / tháng | $60 |
| ~trang/tháng (ước lượng) | ~10.000 |

Nếu hết limit: đợi reset hoặc bật **Use balance** trong console OpenCode.

**Lưu ý auth:** endpoint Anthropic `/messages` của OpenCode Go yêu cầu header `x-api-key` (không chỉ `Authorization: Bearer`). Backend đã gửi đúng format này.

Nếu model Anthropic từ chối ảnh, backend tự fallback `grok-4.5` qua `/chat/completions` (OpenAI format; allowance riêng ~$15, ~$0,013/trang).

## 3. Poppler (render PDF → ảnh)

`pdf2image` gọi `pdftoppm`/`pdfinfo` từ poppler. Trên Windows không cài được poppler qua pip.

**Cách 1 (khuyến nghị):** tải binary từ [oschwartz10612/poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases), giải nén vào `tools/poppler/` sao cho có:

```
tools/poppler/poppler-<ver>/Library/bin/pdftoppm.exe
```

`pdf2md-smart` tự dò thư mục này. Nếu đặt nơi khác, trỏ bằng env `PDF2MD_POPPLER_DIR` hoặc `--poppler-path`.

**Cách 2:** thêm poppler vào PATH hệ thống.

**macOS:** `brew install poppler` — **Linux:** `sudo apt install poppler-utils`

## 4. PaddleOCR (OCR offline, tùy chọn)

Dùng khi không có mạng / không muốn gọi cloud:

```bash
pdf2md-smart tai-lieu.pdf -o out.md --ocr-backend paddleocr
```

### 4.1. Cài paddlepaddle CPU (sau sync)

`paddlepaddle` **không** nằm trong deps chính (wheel CPU/GPU khác nhau). Cài sau `uv sync`:

```bash
uv pip install "paddlepaddle>=3.1.0" -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
```

**Bắt buộc ≥ 3.1.0** — PP-OCRv6 không chạy trên paddle 3.0.0 (lỗi PIR `strides`).

### 4.2. Hạn chế charset tiếng Việt

PaddleOCR PP-OCRv5/v6 **không chứa khối Vietnamese Extended** (U+1EA0–U+1EF9) trong charset recognition — bug upstream ([PaddleOCR #16339](https://github.com/PaddlePaddle/PaddleOCR/issues/16339)). Hệ quả: mất dấu kiểu `Độc lập` → `Đc lp`. Dùng backend `opencode` (mặc định) khi cần dấu đầy đủ.

Lần đầu chạy PaddleOCR sẽ tải model (~vài chục MB).

## 5. Cache OCR / resume

Mặc định mỗi trang OCR được lưu dưới cache local (keyed bởi hash nội dung PDF + options). Chạy lại **cùng lệnh** sẽ bỏ qua trang đã có — continue sau khi dừng (Ctrl+C).

| | |
|---|---|
| Thư mục mặc định | Windows: `%LOCALAPPDATA%\smart-pdf2md\cache\` · Unix: `~/.cache/smart-pdf2md/` |
| Override | env `PDF2MD_CACHE_DIR` |
| Tắt cache | `--no-cache` (không đọc/ghi) |
| Làm mới trang | `--force-ocr` vẫn OCR lại và ghi đè cache |

## 6. Hiệu năng

- **OpenCode VLM**: phụ thuộc mạng + latency model; trả Markdown có heading/bảng tốt hơn Paddle.
- **PaddleOCR CPU**: ~1–3 giây/trang (DPI 150–200).
- Text-based PDF không cần OCR — tốc độ < 300ms/trang.
- Resume từ cache: trang đã OCR không gọi lại backend.

Giảm `--dpi` (ví dụ 150) để nhanh hơn / rẻ hơn (ít pixel gửi VLM).

## 7. Kiểm tra cài đặt

```bash
uv run pdf2md-smart tests/fixtures/input/WB-1.pdf -o out.md          # native, không cần OCR
uv run pdf2md-smart "tests/fixtures/input/Thông-tư-89-2026-TT-BTC.pdf" --page 1-2 -o out.md   # OCR VLM
```

## 8. License

- Code của project: MIT
- [pdf-inspector](https://github.com/firecrawl/pdf-inspector): MIT
- OCR mặc định: OpenCode Go (subscription)
- OCR offline: [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) / PaddlePaddle (Apache-2.0)
