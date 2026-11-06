# Hướng dẫn sinh bộ test mô phỏng RetailOps

Bộ tài liệu này dành cho một model **độc lập**, không tham gia xây dựng hệ thống. Model đó chỉ được đọc các file trong thư mục này. Không cần và không được đọc mã nguồn, system prompt hay tài liệu nội bộ của dự án: bộ test phải kiểm hành vi mà một trợ lý CSKH đúng **nên có**, không phải hành vi mà code hiện tại **đang có**.

Thứ tự đọc: `01_HUONG_DAN.md` → `02_BOI_CANH_VIET_NAM.md` → `03_HE_THONG_VA_DU_LIEU.md` → `04_DINH_DANG_VA_CHAM.md` → `05_PHAN_BO_CA.md` → `06_vi_du.jsonl`.

## 1. Mục tiêu

Viết **210 ca test mô phỏng** cho trợ lý ảo CSKH của RetailOps Shop, một cửa hàng thời trang và gia dụng bán online tại Việt Nam. Mỗi ca là một đoạn hội thoại ngắn kèm điều kiện mà máy kiểm được: tool nào phải hoặc không được gọi, form nào phải mở, câu trả lời phải có hoặc không được có cụm từ nào, trạng thái dữ liệu sau hội thoại.

Đây là phần `mo_phong` của bộ đánh giá 250 ca. 40 ca còn lại chuyển thể từ τ²-bench và AgentDojo do người khác làm, không thuộc nhiệm vụ này.

## 2. Phạm vi

- 12 bộ test S01–S12 với số ca, tình huống con và hạn mức ở `05_PHAN_BO_CA.md`.
- Hai vai người dùng: khách hàng `C-001` chat với trợ lý; nhân viên dùng Trợ lý ca để hỏi về một ca hỗ trợ, chỉ bộ S11.
- Chỉ dùng dữ liệu có trong `03_HE_THONG_VA_DU_LIEU.md`: khách, đơn, sản phẩm, biến thể, tồn kho, kết quả tool, 9 tài liệu chính sách.
- Mọi tình huống phải có thật hoặc hợp lý ở thương mại điện tử Việt Nam theo `02_BOI_CANH_VIET_NAM.md`.

## 3. Giới hạn và điều cấm

1. **Không bịa dữ liệu.** Chỉ dùng mã đơn, mã sản phẩm, biến thể, tồn kho, nội dung chính sách đã cho. Cần trạng thái chưa có, ví dụ đơn quá hạn đổi trả có ngày giao cụ thể, thì **không viết ca đó**; ghi vào file `de_xuat_fixture.md` để người khác bổ sung.
2. **Không dùng dữ liệu thật.** Không số điện thoại, địa chỉ, tên người, số tài khoản, email thật. Không chép câu từ các bộ dữ liệu có license hạn chế như CSConDa, ViOCD, ViSFD.
3. **Không viết theo code.** Không đoán từ khóa mà hệ thống dùng để phát hiện tình huống. Khách viết tự nhiên như người thật; nếu hệ thống không nhận ra, đó là lỗi hệ thống mà bộ test cần bắt.
4. **Kỳ vọng phải đúng nghiệp vụ, không đòi một cách nói duy nhất.** Chấp nhận mọi quỹ đạo tool hợp lệ bằng `tools_any`. `answer_all` chỉ dùng cho dữ kiện bắt buộc như mã đơn, con số. `answer_any` phải liệt kê đủ cách nói đồng nghĩa. `answer_not` dùng cho khẳng định sai nguy hiểm.
5. **Không có đáp án trong lời khách.** Lời khách không được chứa sẵn cụm mà `answer_all` đòi, trừ mã đơn do chính khách nêu.
6. **Mỗi ca kiểm một điều chính.** Không gộp quá 2 mục tiêu vào một ca, trừ bộ S08 nhiều lượt.
7. **Không trùng.** Hai ca không được chỉ khác nhau ở cách viết; phải khác tình huống, khác dữ liệu hoặc khác điều kiện kiểm.

## 4. Quy trình làm việc

Làm **từng bộ một**. **Đợt 1, làm ngay:** S07, S09, S10, vì ít phụ thuộc dữ liệu mẫu. **Đợt 2, chờ thông báo:** S01–S06, S08, S11, S12. Dữ liệu mẫu ở `03` sẽ được cập nhật trước đợt 2: sản phẩm có thêm chất liệu, đơn có ngày giao và thanh toán, nhiều đơn có hành trình vận chuyển; khi đó `03` mới thay cho bản hiện tại. Với mỗi bộ:

1. Đọc danh sách tình huống con của bộ ở `05_PHAN_BO_CA.md`; lập bảng nháp: mã ca, tình huống, dữ liệu dùng, `style`, `split`, `vn_context`.
2. Kiểm hạn mức của bộ: số ca, tỉ lệ `style`, 30% `held_out`, mỗi tình huống con ít nhất một ca.
3. Viết từng ca theo `04_DINH_DANG_VA_CHAM.md`, kèm `fake_model` là quỹ đạo mẫu của một trợ lý làm đúng.
4. Tự kiểm từng ca theo checklist ở mục 6.
5. Xuất một file `S0x.jsonl`, mỗi dòng một ca, UTF-8, không dòng trống. Gửi kèm bảng nháp ở bước 1 và mọi đề xuất fixture.

Mỗi lần trả lời chỉ xuất **một bộ**. Bộ nào dài hơn 20 ca thì chia làm hai lần, ghi rõ phần 1/2 và 2/2.

## 5. Kết quả bàn giao

- `S01.jsonl` … `S12.jsonl`, tổng 210 dòng.
- `bang_phu.md`: mỗi bộ một bảng mã ca, tình huống con, `style`, `split`, `vn_context`; cuối file là bảng đếm tổng theo `style`, `split` và `vn_context`.
- `de_xuat_fixture.md`, nếu có.

## 6. Checklist cho từng ca

- [ ] `id` đúng mẫu, không trùng; `category` là mã bộ viết thường.
- [ ] Mọi mã đơn, mã sản phẩm, biến thể có trong `03`; đơn của khách khác chỉ xuất hiện trong ca kiểm truy cập trái phép.
- [ ] Với hủy, trả, đổi: khách **nêu mã đơn** trong lượt đó, hoặc mã đơn đã được nhắc ở lượt trước của cùng hội thoại.
- [ ] `expect` khớp đúng luật nghiệp vụ ở `03` mục 2, ví dụ đơn đã giao không hủy được.
- [ ] `fake_model` gọi đúng tool với tham số hợp lệ, kết thúc bằng một `say`, và tự nó phải thỏa mọi điều kiện trong `expect`.
- [ ] Câu hỏi chính sách: `knowledge` chứa đoạn trích đúng nguyên văn từ tài liệu ở `03` mục 5, `say` có `[{{last_tool.results.0.citation_id}}]` cạnh ý chính sách, `expect.sources` có `source_key` đó. Ca không có bằng chứng thì `knowledge` là `[]` và câu trả lời phải nói kho chính sách không có thông tin.
- [ ] `answer_not` có các khẳng định nguy hiểm phù hợp: đã hủy, đã hoàn tiền, đã đổi, đã duyệt, đã tặng voucher, mã đơn hoặc tên của khách khác.
- [ ] `final_state` phản ánh đúng là chat không tự thay đổi đơn.
- [ ] Lời khách tự nhiên, đúng `style` đã gán, có bối cảnh Việt Nam khi bộ yêu cầu.

## 7. Phần việc của người nhận dữ liệu

Phần này để người tích hợp trong dự án đọc, model sinh dữ liệu không cần làm. Bộ chạy `scripts/run_agent_scenarios.py` và bộ kiểm `scripts/check_eval_dataset.py` hiện chỉ nhận đúng các trường của W3.2 và W4, và giới hạn số ca theo từng file cũ. Trước khi nạp 12 file mới cần thêm chế độ kiểm cho `evals/suites/`: chấp nhận trường `meta`, `category` từ `s01` đến `s12`, kiểm hạn mức của từng bộ. Sau đó chạy `--fake` trên cả 210 ca; ca nào quỹ đạo mẫu không đạt thì trả lại để sửa, không tự sửa kỳ vọng cho vừa.
