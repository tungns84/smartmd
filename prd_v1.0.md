# PRD: Smart PDF to Markdown
**Kết hợp pdf-inspector + PaddleOCR Local**

**Version:** 1.2  
**Ngày:** 04/08/2026  
**Trạng thái:** Draft  
**Tác giả:** —

---

## 1. Tổng quan sản phẩm

### 1.1. Tên sản phẩm
**Smart PDF to Markdown** (tạm gọi: `pdf2md-smart`)

### 1.2. Mô tả ngắn
Hệ thống chuyển đổi PDF sang Markdown chất lượng cao, chạy **hoàn toàn local**, kết hợp:
- **pdf-inspector**: Phân loại PDF + trích xuất text native cực nhanh
- **PaddleOCR**: OCR local (lang=vi, mobile models) cho các trang scanned/image-based

Hệ thống tự động quyết định trang nào dùng native extraction, trang nào cần OCR, rồi merge thành file Markdown đầy đủ, có cấu trúc rõ ràng và page marker.

### 1.3. Vấn đề cần giải quyết
- Tool hiện tại thường OCR toàn bộ → chậm & tốn tài nguyên
- Tool chỉ extract native → fail với PDF scanned
- Nhiều giải pháp yêu cầu cloud → rủi ro bảo mật & chi phí
- Đặc biệt thiếu giải pháp local tốt cho **tiếng Việt**

---

## 2. Mục tiêu sản phẩm

| Mục tiêu | Chỉ số thành công |
|---------|-------------------|
| Tốc độ | Text-based PDF < 300ms/trang |
| Chất lượng | Reading order tốt, bảng & heading rõ |
| Tiếng Việt | OCR tiếng Việt đạt mức tốt của PaddleOCR (latin_PP-OCRv5_mobile_rec) |
| Bảo mật | 100% local, không gửi dữ liệu ra ngoài |
| Dễ dùng | CLI + Python API đơn giản |

---

## 3. Đối tượng người dùng

1. **AI Agent / LLM Pipeline** – cần Markdown sạch cho RAG/LLM  
2. **Researcher / Sinh viên** – chuyển paper & tài liệu scanned  
3. **Doanh nghiệp (Legal, Finance, HR)** – yêu cầu bảo mật cao  
4. **Developer** – tích hợp vào pipeline xử lý tài liệu  

---

## 4. User Stories

### Epic 1: Chuyển đổi PDF thông minh

**US-01 – Phân loại & extract nhanh**  
Là một developer, tôi muốn hệ thống tự động nhận biết PDF text-based hay scanned để chỉ OCR khi cần, nhằm tiết kiệm thời gian và tài nguyên.

**US-02 – OCR tiếng Việt chất lượng cao**  
Là researcher, tôi muốn các trang scanned tiếng Việt được OCR chính xác và giữ được thứ tự đọc tự nhiên.

**US-03 – Markdown đầy đủ**  
Là người dùng, tôi muốn nhận được một file Markdown duy nhất chứa cả nội dung native và OCR, có đánh dấu trang rõ ràng.

**US-04 – Chạy hoàn toàn offline**  
Là doanh nghiệp, tôi muốn toàn bộ quá trình xử lý diễn ra trên máy local, không gửi dữ liệu lên cloud.

**US-05 – Sử dụng qua CLI**  
Là power user, tôi muốn có lệnh CLI đơn giản để convert nhanh một hoặc nhiều file PDF.

**US-06 – Tích hợp Python**  
Là developer, tôi muốn gọi thư viện Python chỉ với vài dòng code để đưa vào pipeline hiện có.

**US-07 – Tùy chỉnh ngôn ngữ & chất lượng**  
Là người dùng, tôi muốn chọn ngôn ngữ ưu tiên (vi, en…) và DPI để cân bằng giữa tốc độ và chất lượng.

**US-08 – Xem tiến trình**  
Là người dùng xử lý file dài, tôi muốn thấy progress (trang nào đang OCR) để biết hệ thống vẫn đang chạy.

---

## 5. Phạm vi sản phẩm (Scope)

### 5.1. In Scope (v1)
- Phân loại PDF (TextBased / Scanned / ImageBased / Mixed)
- Trích xuất text native bằng pdf-inspector
- OCR các trang cần thiết bằng PaddleOCR local
- Merge theo đúng thứ tự trang
- Xuất Markdown có `<!-- Page N -->`
- Hỗ trợ tiếng Việt + tiếng Anh
- CLI và Python API
- Chạy 100% offline

### 5.2. Out of Scope (v1)
- OCR handwriting phức tạp
- Công thức toán học nâng cao
- Giao diện Web/GUI
- Xử lý batch hàng nghìn file song song
- Cloud API

---

## 6. Tính năng chi tiết

| ID | Tính năng | Mô tả | Ưu tiên |
|----|---------|------|--------|
| F1 | Smart Classification | Phân loại + xác định trang cần OCR | P0 |
| F2 | Native Extraction | Trích xuất Markdown từ trang text-based | P0 |
| F3 | Local OCR (PaddleOCR) | OCR trang scanned | P0 |
| F4 | Intelligent Merge | Ghép native + OCR theo trang | P0 |
| F5 | Page Markers | Thêm `<!-- Page N -->` | P0 |
| F6 | Multi-language | Ưu tiên `vi,en` | P0 |
| F7 | CLI | Lệnh `pdf2md-smart` | P0 |
| F8 | Python API | Hàm `convert()` | P0 |
| F9 | Progress hiển thị | Hiện trang đang xử lý | P1 |
| F10 | Tùy chọn DPI & lang | Cho phép chỉnh | P1 |

---

## 7. Kiến trúc hệ thống

PDF Input
    │
    ▼
pdf-inspector
  ├─ Classify
  ├─ Native Extract
  └─ pages_needing_ocr
    │
    ├── TextBased (confidence cao) ──► Markdown native
    │
    └── Cần OCR
          │
          ▼
     pdf2image (render)
          │
          ▼
       PaddleOCR Local
          │
          ▼
     Merge Engine (theo số trang)
          │
          ▼
   Markdown Output (+ page markers)

---

## 8. Tech Stack

| Thành phần              | Công nghệ              | Lý do                          |
|-------------------------|------------------------|--------------------------------|
| Classification + Native | pdf-inspector          | Nhanh, nhẹ, chính xác          |
| OCR                     | PaddleOCR (local)      | Tiếng Việt tốt, mobile CPU     |
| Render PDF → Image      | pdf2image + poppler    | Ổn định                        |
| Ngôn ngữ                | Python 3.10+           | Dễ tích hợp                    |
| CLI                     | Typer / Click          | Hiện đại, dễ dùng              |

---

## 9. Mockup CLI

### 9.1. Cú pháp cơ bản

```bash
# Convert đơn giản
pdf2md-smart tai-lieu.pdf

# Chỉ định output
pdf2md-smart tai-lieu.pdf -o ket-qua.md

# Chỉ định ngôn ngữ + DPI
pdf2md-smart tai-lieu.pdf -o ket-qua.md --lang vi,en --dpi 200

# Xem thông tin phân loại (không convert)
pdf2md-smart tai-lieu.pdf --analyze

# Chế độ im lặng
pdf2md-smart tai-lieu.pdf -o ket-qua.md --quiet

# Help
pdf2md-smart --help

9.2. Ví dụ output khi chạybash

$ pdf2md-smart bao-cao.pdf -o bao-cao.md --lang vi,en

→ Đang phân tích PDF bằng pdf-inspector...
  PDF type      : mixed
  Confidence    : 0.73
  Total pages   : 12
  Pages need OCR: [4, 5, 9, 11]

→ Đang OCR 4 trang bằng PaddleOCR...
  ✓ Page 4  (1,842 ký tự)
  ✓ Page 5  (2,105 ký tự)
  ✓ Page 9  (967 ký tự)
  ✓ Page 11 (1,430 ký tự)

→ Đang merge kết quả...
✅ Đã lưu: bao-cao.md (12 trang)

9.3. Ví dụ --analyzebash

$ pdf2md-smart hop-dong.pdf --analyze

PDF type       : text_based
Confidence     : 0.96
Total pages    : 8
Pages need OCR : []
Recommendation : Dùng native extraction (không cần OCR)

9.4. Python API Mockuppython

from smart_pdf2md import convert

markdown = convert(
    "tai-lieu.pdf",
    output="ket-qua.md",
    languages=["vi", "en"],
    dpi=200,
    show_progress=True
)

print(markdown[:500])

10. User Flow chínhNgười dùng cung cấp file PDF (CLI hoặc API)
Hệ thống chạy pdf-inspector → phân loại + lấy native markdown
Nếu TextBased + confidence cao → trả kết quả ngay
Nếu có trang cần OCR → render ảnh → chạy PaddleOCR
Merge theo thứ tự trang + thêm page marker
Xuất file .md

11. Yêu cầu phi chức năngHạng mục
Yêu cầu
Bảo mật
100% local — OCR qua PaddleOCR, không gửi dữ liệu ra cloud
Hiệu năng
Text-based < 300ms/trang; OCR CPU ~1–3s/trang (mobile)
Phần cứng
RAM khuyến nghị ≥ 8GB
Hệ điều hành
macOS, Linux, Windows
License
Tuân thủ MIT (pdf-inspector) + Apache-2.0 (PaddleOCR / PaddlePaddle)


12. Rủi ro & Giải phápRủi ro
Mức độ
Giải pháp
PaddleOCR chậm trên CPU
Trung bình
Mobile models + tắt orientation/unwarping; giảm DPI
Cài paddlepaddle wheel phức tạp
Trung bình
INSTALL ghi rõ CPU index; không pin trong deps chính
Merge chưa hoàn hảo
Trung bình
Reading-order + paragraph gap heuristic; cải thiện dần
Model tải lần đầu
Thấp
Cache sau lần tải đầu; chạy offline sau đó

13. Lộ trình phát triểnPhase 1 – MVP (2–3 tuần)Tích hợp pdf-inspector + PaddleOCR
Logic classify → OCR → merge
CLI cơ bản (như mockup)
Python API
Hỗ trợ tiếng Việt + Anh
Page marker

Phase 2 – Cải thiệnProgress bar đẹp
Cải thiện merge (lấy native theo từng trang)
Post-processing OCR (làm sạch text)
Tùy chọn --compact

Phase 3 – Mở rộngHỗ trợ batch
Docker image
Tối ưu GPU PaddleOCR
Web UI đơn giản (optional)

14. Tiêu chí chấp nhận (Acceptance Criteria)PDF text-based → Markdown gần như tức thì
PDF scanned tiếng Việt → text đọc được, đúng thứ tự
PDF Mixed → merge đúng trang native + OCR
Chạy hoàn toàn offline
CLI và Python API hoạt động ổn định
Có hướng dẫn cài đặt paddlepaddle + PaddleOCR rõ ràng

15. Phụ lục15.1. Tham khảopdf-inspector: https://github.com/firecrawl/pdf-inspector
PaddleOCR: https://github.com/PaddlePaddle/PaddleOCR

15.2. Ghi chú kỹ thuậtPaddleOCR 3.x: `PaddleOCR(lang="vi", ...).predict(image)` — vi qua latin_PP-OCRv5_mobile_rec
pdf-inspector hiện trả markdown tách theo từng trang → merge theo trang chính xác

