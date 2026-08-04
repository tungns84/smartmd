# Hướng dẫn cài đặt

`pdf2md-smart` chạy 100% local. Cần 3 phần: Python env, poppler (render PDF→ảnh), và Surya 2 + llama.cpp (OCR).

## 1. Python environment

Yêu cầu: Python 3.10+ (khuyến nghị 3.12), [uv](https://docs.astral.sh/uv/).

```bash
uv sync --group dev
```

`uv sync` cài `pdf-inspector`, `surya-ocr` (kèm torch ~2GB), `pdf2image`, `typer`, `rich`.

## 2. Poppler (render PDF → ảnh)

`pdf2image` gọi `pdftoppm`/`pdfinfo` từ poppler. Trên Windows không cài được poppler qua pip.

**Cách 1 (khuyến nghị):** tải binary từ [oschwartz10612/poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases), giải nén vào `tools/poppler/` sao cho có:

```
tools/poppler/poppler-<ver>/Library/bin/pdftoppm.exe
```

`pdf2md-smart` tự dò thư mục này. Nếu đặt nơi khác, trỏ bằng env `PDF2MD_POPPLER_DIR` hoặc `--poppler-path`.

**Cách 2:** thêm poppler vào PATH hệ thống.

**macOS:** `brew install poppler` — **Linux:** `sudo apt install poppler-utils`

## 3. Surya 2 + llama.cpp (OCR)

Surya 2 là VLM 650M, cần inference backend: **llama.cpp** (CPU/Apple Silicon) hoặc **vllm** (NVIDIA GPU).

### 3.1. Tải llama-server

- **Windows:** tải `llama-bXXXX-bin-win-cpu-x64.zip` (hoặc bản `win-cuda` nếu có GPU NVIDIA) từ [ggml-org/llama.cpp/releases](https://github.com/ggml-org/llama.cpp/releases), giải nén vào `tools/llama.cpp/` sao cho có `tools/llama.cpp/llama-server.exe`. `pdf2md-smart` tự dò.
- **macOS:** `brew install llama.cpp`
- **Linux:** `brew install llama.cpp` hoặc dùng release zip như Windows.

Hoặc set env `LLAMA_CPP_BINARY=/đường/dẫn/llama-server`.

### 3.2. Model GGUF (tải 1 lần, cache vào `~/.cache/huggingface`)

Lần đầu chạy OCR, Surya tự tải `surya-2.gguf` (~1.2GB) + `surya-2-mmproj.gguf` (~200MB) từ HuggingFace. Sau đó chạy hoàn toàn offline. Muốn tải trước:

```bash
python -c "from huggingface_hub import hf_hub_download; print(hf_hub_download('datalab-to/surya-ocr-2-gguf','surya-2.gguf')); print(hf_hub_download('datalab-to/surya-ocr-2-gguf','surya-2-mmproj.gguf'))"
```

### 3.3. Hai cách chạy OCR

**Cách A — tự động (mặc định):** `pdf2md-smart` tự spawn llama-server khi cần và tự tắt khi xong. Model nạp lại mỗi lần chạy (~30-60s).

**Cách B — server riêng (khuyến nghị khi xử lý nhiều file):**

```bash
llama-server -m ~/.cache/huggingface/hub/models--datalab-to--surya-ocr-2-gguf/snapshots/<commit>/surya-2.gguf \
  --mmproj .../surya-2-mmproj.gguf --alias datalab-to/surya-ocr-2 \
  --host 127.0.0.1 --port 8000 --parallel 4
```

```bash
export SURYA_INFERENCE_URL=http://127.0.0.1:8000/v1   # Windows: $env:SURYA_INFERENCE_URL=...
```

## 4. Hiệu năng OCR

| Phần cứng | Tốc độ ước tính |
|---|---|
| CPU (14 cores, đo thực tế) | ~280-365 giây/trang @ 200 DPI |
| NVIDIA GPU (vllm) | ~5 trang/giây (RTX 5090, theo Surya) |
| Apple Silicon (Metal) | nhanh hơn CPU đáng kể |

Giảm `--dpi` (ví dụ 150) giảm ~25% thời gian, chất lượng giảm nhẹ. Với file scanned dài, dùng `--page 1-50` xử lý theo lô. Text-based PDF (đa số báo cáo, văn bản) không cần OCR — tốc độ < 300ms/trang.

## 5. Kiểm tra cài đặt

```bash
uv run pdf2md-smart tests/fixtures/input/WB-1.pdf -o out.md          # native, không cần OCR
uv run pdf2md-smart "tests/fixtures/input/Thông-tư-89-2026-TT-BTC.pdf" --page 1-2 -o out.md   # có OCR
```

## 6. License

- Code của project: MIT
- [pdf-inspector](https://github.com/firecrawl/pdf-inspector): MIT
- [Surya](https://github.com/datalab-to/surya): code Apache-2.0, weights **OpenRAIL-M (modified)** — miễn phí cho nghiên cứu, sử dụng cá nhân và startup có doanh thu dưới $5M. Kiểm tra [license](https://huggingface.co/datalab-to/surya-ocr-2) trước khi dùng thương mại quy mô lớn.
- llama.cpp: MIT
