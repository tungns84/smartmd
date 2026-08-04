import argparse
from pathlib import Path

from smart_pdf2md import analyze, convert_full

DEFAULT_CHUNK = 20


def _iter_chunks(start: int, end: int, chunk: int):
    for first in range(start, end + 1, chunk):
        yield first, min(first + chunk - 1, end)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="batch_ocr",
        description="OCR PDF theo lô trang (giảm thời gian mỗi lần chạy, tiết kiệm RAM).",
    )
    parser.add_argument("pdf", help="File PDF")
    parser.add_argument("-o", "--out-dir", default="out", help="Thư mục chứa kết quả (mặc định: out/)")
    parser.add_argument("--chunk", type=int, default=DEFAULT_CHUNK, help=f"Số trang mỗi lô (mặc định: {DEFAULT_CHUNK})")
    parser.add_argument("--dpi", type=int, default=200, help="DPI cho OCR")
    parser.add_argument("--force-ocr", action="store_true", help="Ép OCR toàn bộ mọi trang")
    parser.add_argument("--combine", action="store_true", help="Gộp tất cả lô thành 1 file .md")
    parser.add_argument("--start", type=int, default=1, help="Bắt đầu từ trang số (1-indexed)")
    parser.add_argument("--end", type=int, default=None, help="Kết thúc ở trang (mặc định: trang cuối)")
    args = parser.parse_args()

    pdf = Path(args.pdf)
    if not pdf.exists():
        parser.error(f"Không tìm thấy file: {pdf}")

    info = analyze(pdf)
    total = args.end or info.page_count
    if args.start > total:
        parser.error("--start lớn hơn số trang")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    chunk_files: list[Path] = []

    print(f"PDF: {pdf} | {info.pdf_type} | {info.page_count} trang | OCR pages: {len(info.pages_needing_ocr)}")
    print(f"Xử lý trang {args.start}-{total}, mỗi lô {args.chunk} trang, DPI {args.dpi}")

    for first, last in _iter_chunks(args.start, total, args.chunk):
        out_file = out_dir / f"{pdf.stem}-p{first:04d}-{last:04d}.md"
        chunk_files.append(out_file)
        print(f"\n→ Lô {first}-{last} → {out_file}")
        convert_full(
            pdf,
            output=out_file,
            dpi=args.dpi,
            force_ocr=args.force_ocr,
            show_progress=True,
            pages=list(range(first, last + 1)),
        )
        print(f"   ✓ Xong: {out_file}")

    if args.combine:
        final = out_dir / f"{pdf.stem}.md"
        parts = []
        for f in chunk_files:
            if f.exists():
                parts.append(f.read_text(encoding="utf-8").strip())
        final.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
        print(f"\nĐã gộp: {final}")

    print("\nXong tất cả lô.")


if __name__ == "__main__":
    main()