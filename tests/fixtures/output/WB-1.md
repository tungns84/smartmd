<!-- Page 1 -->

# Workbook – Day 1

## From Traditional SDLC to AI-Driven Software Engineering – Where should we use AI?

## Thời lượng: 60 minutes

## Tổ

<!-- Page 2 -->

|Mục tiêu Sau activity này, nhóm cần: • • • • • Chuẩn bị đầu vào cho Activity 2. Bối cảnh • Business Analyst tiếp nhận yêu cầu. • Architect thiết kế giải pháp. • Developer hiện thực chức năng. • Tester xây dựng test case và kiểm thử. • Technical Lead review trước khi triển khai. ChatGPT, Claude, Copilot, Gemini...), tuy nhiên các AI này việc dựa trên thông tin mà người dùng cung cấp. Câu hỏi đặt ra là: để AI và con người có thể cộng tác hiệu quả? Nhiệm vụ|Activity 1 – Phân tích quy trình SDLC hiện tại và các điểm đứt gãy thông tin (20p) Hiểu quy trình SDLC hiện tại khi phát triển chức năng mới. Xác định các artifacts được tạo ra ở từng phase. Phân tích những thông tin cần được chuyển giao giữa các phase. Xác định các điểm có nguy cơ mất thông tin (Context Drift). Sau khi nhận được yêu cầu thay đổi từ bệnh viện, nhóm phát triển bắt đầu triển khai chức năng mới. Quy trình hiện tại của công ty vẫn là quy trình SDLC truyền thống. Hiện tại mỗi thành viên đều có thể sử dụng một AI Assistant riêng để hỗ trợ công việc của mình (ví dụ Trong quy trình này, những thông tin nào cần được duy trì xuyên suốt giữa các phase Bước 1: Chọn những thông tin quan trọng nhất, giả sử ở các phase Requirement Analysis, Design, Development có những thông tin sau được tạo ra:|không chia sẻ ngữ cảnh với nhau|và chỉ làm|
|---|---|---|---|
|Requirement Analysis|Design|Development||
|□ Business goals|□ Architecture Decision|□ Source code||
|□ Functional requirements|□ API Contracts|□ Logging||
|□ Business rules|□ Database Schema|□ Exception Handling||
|□ User stories|□ Component Responsibilities|□ Configuration||
|□ Acceptance criteria|□ Design Constraints|□ Known Limitations||
|□ Priority|□ Technology Stack|□ Technical Assumptions||
|□ Business constraints|□|||

<!-- Page 3 -->

## Bước 2: Giả sử các tình huống sau

1) Developer cần thông tin nào nhất, theo nhóm điều gì có thể xảy ra với kết quả từ AI nếu không có thông tin đó?
2) Tester cần thông tin nào nhất, điều gì xảy ra nếu không có hoặc không đủ?
3) Architect cần thông tin nào nhất, điều gì xảy ra nếu không có hoặc không đủ?
**Bước 3: Tổng hợp, sau khi hoàn thành hãy thống nhất 03 thông tin quan trọng nhất cần được** **duy trì xuyên suốt SDLC** Thứ hạng **Thông tin Vì sao** **1** **2** **3**

## Bước 4: Thảo luận nhóm

Câu hỏi 1: Trong SDLC phase nào tạo ra nhiều thông tin quan trọng nhất? Tại sao Câu hỏi 2: Thông tin nào dễ bị mất nhất khi chuyển giao giữa các phase? Câu hỏi 3: Theo nhóm nguyên nhân lớn nhất khiến các nhóm phát triển phải rework là gì Câu hỏi 4: Khi mỗi phase chúng ta sử dụng 1AI Assistant khác nhau, AI nào sẽ gặp khó khăn nhất? Tại sao **Deliverables: Mỗi nhóm chuẩn bị 01 slide để tóm lược các thông tin trong 4 bước nói trên. Trình** **bày thảo luận trong 05 phút.**

<!-- Page 4 -->

|Mục tiêu Sau activity này, học viên có thể: • • nhiệm • trách nhiệm cuối cùng • Bối cảnh với sự cộng tác Human-AI Bước 1: AI nên tham gia ở đâu|Activity 2: Thiết kế mô hình Human-AI Collaboration cho SDLC (30p) Xác định những hoạt động AI có thể hỗ trợ hiệu quả trong từng phase của SDLC Hiểu khái niệm Human-in-the-loop và Human-on-the-loop trong SDLC Sau Activity 1, những thông tin quan trọng nhất cần được duy trì xuyên suốt SDLC đã được xác định, điều này giúp cho cả Human và AI cùng luôn nắm được ngữ cảnh. Tiếp theo sẽ thiết kế quy trình SDLC|Phân biệt những quyết định AI nên thực hiện và những quyết định con người vẫn cần chịu trách Hiểu khi nào AI nên đề xuất, khi nào AI có thể tự động thực hiện và khi nào con người phải chịu||
|---|---|---|---|
|Hoạt động|AI không nên tham gia|AI hỗ trợ|AI có thể tự động|
|Phân tích yêu cầu|□|□|□|
|Sinh User Story|□|□|□|
|Đề xuất kiến trúc|□|□|□|
|Sinh API|□|□|□|
|Sinh mã nguồn|□|□|□|
|Sinh Unit Test|□|□|□|
|Code Review|□|□|□|
|Security Review|□|□|□|
|Sinh tài liệu|□|□|□|
|Release lên production|□|□|□|

1) 2) Với mỗi phase của SDLC, hãy xác định: • AI chịu trách nhiệm gì? • Human chịu trách nhiệm gì? • Vì sao Hoạt động nào AI mang lại nhiều giá trị nhất? Hoạt động nào AI có nhiều rủi ro nhất? Bước 2: Phân chia trách nhiệm giữa AI và Human

<!-- Page 5 -->

|Human-AI Responsibility Matrix||||
|---|---|---|---|
|Phase|AI responsibility|Human responsibility|Vì sao?|
|Requirement Analysis||||
|Design||||
|Development||||
|Testing||||
|Code Review||||
|Deployment||||
|Instructions: Hãy mô tả AI có thể làm gì? • • • từng quyết định. Requirement Engineering|Bước 3: Quyết định nào AI không nên thay thế con người Đối với các hoạt động dưới đây, hãy thảo luận và đánh giá: AI có thể quyết định: AI có thể tự động thực hiện mà không cần con người phê duyệt Ai chỉ đề xuất: AI đưa ra gợi ý, con người xem xét và quyết định Human quyết định: quyết định bắt buộc phải do con người phụ trách Lưu ý: Không có đáp án đúng duy nhất. Nhóm lựa chọn trên mức độ rủi ro, trách nhiệm và tác động của|||
|Quyết định|AI có thể quyết định|AI chỉ đề xuất|Human quyết định|
|Làm rõ yêu cầu|□|□|□|
|Sinh user stories|□|□|□|
|Sinh acceptance criteria|□|□|□|
|Ưu tiên trong Backlog|□|□|□|
|Thay đổi business rules|□|□|□|
|Chấp nhận requirement|□|□|□|
|System Design||||
|Quyết định|AI có thể quyết định|AI chỉ đề xuất|Human quyết định|
|Đề xuất kiến trúc|□|□|□|
|Chọn công nghệ|□|□|□|
|Thiết kế API|□|□|□|
|Thiết kế Database|□|□|□|
|Thiết kế Security|□|□|□|
|Phê duyệt Architecture|□|□|□|

<!-- Page 6 -->

Development

|Quyết định|AI có thể quyết định|AI chỉ đề xuất|Human quyết định|
|---|---|---|---|
|Sinh mã nguồn|□|□|□|
|Refactoring|□|□|□|
|Sinh tài liệu kĩ thuật|□|□|□|
|Chỉnh sửa code hiện có|□|□|□|
|Merge Pull request|□|□|□|
|Commit trực tiếp vào main branch|□|□|□|

## Testing & Quality Assurance

|Quyết định|AI có thể quyết định|AI chỉ đề xuất|Human quyết định|
|---|---|---|---|
|Sinh test cases|□|□|□|
|Sinh test data|□|□|□|
|Phát hiện bug|□|□|□|
|Đóng bug|□|□|□|

<!-- Page 7 -->

|Đề xuất thời điểm Release||□|□||□|
|---|---|---|---|---|---|
|Triển khai Production||□|□||□|
|Rollback phiên bản||□|□||□|
|Xử lý Incident||□|□||□|
|Phê duyệt Hotfix Câu hỏi thảo luận: : Quan sát toàn bộ SDLC, nhóm nhận thấy: Q1 Phase nào AI có thể tự động hoá nhiều nhất Q2: chịu trách nhiệm Giải thích. Bước 4: Phân biệt HITL và HOTL|Phase nào cần có sự tham gia của con người nhiều nhất? Vì sao? 1._________________________________________ 2._________________________________________ 3._________________________________________ 4.1. Xác định mô hình phù hợp với các tình huống dưới đây:|□|□ Trong các quyết định trên, nhóm hãy ranking 3 quyết định quan trọng nhất luôn phải do con người||□|
|Tình huống||Human in the loop|||Human on the loop|
|AI sinh user story, BA kiểm tra trước khi sử dụng||□|||□|
|AI sinh Acceptance criteria, BA phê duyệt||□|||□|
|AI đề xuất kiến trúc, Architect phê duyệt||□|||□|
|AI sinh mã nguồn, Developer review trước khi merge||□|||□|
|AI review Pull request, Developer chỉ kiểm tra các cảnh báo||□|||□|
|AI sinh unit test, developer chỉ xem khi test thất bại||□|||□|
|AI tự động sinh tài liệu kỹ thuật||□|||□|
|AI tự động deploy Production||□|||□|
|AI tự động rollback khi phát hiện lỗi||□|||□|

<!-- Page 8 -->

*4.2. Điều gì quyết định mức độ tự động hoá?* Giả sử trong tương lai AI ngày càng chính xác hơn, theo nhóm, điều kiện nào cần được đáp ứng trước khi một hoạt động có thể chuyển từ Human-in-the-loop sang Human-on-the-loop? Hãy đánh dấu những tiêu chí quan trọng nhất. **Tiêu chí Chọn** **AI có độ chính xác cao và ổn định**□ **AI có confidence score rõ ràng**□ **AI có khả năng giải thích kết quả**□ **Có cơ chế Audit Log**□ **Có khả năng Rollback khi xảy ra lỗi**□ **Có dữ liệu lịch sử đủ lớn**□ **Cơ cơ chế Human Feedback liên tục**□ **Có quy trình kiểm soát chất lượng**□ **Quyết định có mức độ rủi ro thấp**□ **Quyết định dễ khôi phục nếu sai**□ 3 tiêu chí quan trọng nhất là gì?
**1.**
**2.**
**3.**
## Deliverables: Mỗi nhóm chuẩn bị 01 slide gồm các nội dung sau

1. Human-AI Responsibility Matrix
2. 3 quyết định quan trọng luôn phải do Human quyết định
3. 3 hoạt động luôn cần Human-in-the-loop
4. 3 hoạt động cần chuyển sang Human-on-the-loop
5. AI Governance Principles – Hoành thành các phát biểu sau
AI chỉ được phép tự động quyết định khi Các quyết định liên quan đến nghiệp vụ phải Các quyết định liên quan đến kiến trúc, chất lượng và an toàn phải Mọi quyết định do AI thực hiện cần Trong trường hợp AI và con người có kết quả khác nhau
