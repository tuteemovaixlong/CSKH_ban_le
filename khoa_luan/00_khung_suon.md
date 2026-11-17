# Khung sườn khóa luận

Cập nhật 2026-11-17 (lần 4): **owner chốt lý thuyết phải kỹ (loss, hàm mất mát, nền tảng) và mã kèm giải thích phải kỹ**, vì hội đồng học thuật sẽ soi; giữ các bổ sung của góp ý Gemini Carbon (mô hình mối đe dọa, phân loại lỗi, ablation, phễu dữ liệu, yêu cầu có ngưỡng, vận hành, gọi đúng tên kỹ thuật), không theo phần cắt lý thuyết và cắt mã. Đặc tả lý thuyết: [09_co_so_ly_thuyet_chi_tiet.md](09_co_so_ly_thuyet_chi_tiet.md); bản đồ mã: [08_ma_nguon_minh_hoa.md](08_ma_nguon_minh_hoa.md).

Ngành Khoa học máy tính, chuyên ngành Trí tuệ nhân tạo. **Cấu trúc CDIO 4 chương + Mở đầu + Kết luận** (đúng như Mở đầu đã viết), văn phong luận văn AI: bài toán hình thức, câu hỏi nghiên cứu, baseline, chỉ số, ablation, phân tích lỗi, mối đe dọa tính hợp lệ.

Đề tài: **XÂY DỰNG HỆ THỐNG TRỢ LÝ ẢO TÍCH HỢP AI HỖ TRỢ CHĂM SÓC KHÁCH HÀNG CHO KINH DOANH BÁN LẺ**

## Nguyên tắc viết

1. **Lý thuyết kỹ nhưng không sách vở:** mỗi khái niệm trình bày bằng công thức, có dẫn xuất ngắn và **ví dụ số lấy từ chính hệ thống** (KV cache 32 KiB/token, LoRA 43.278.336 tham số đếm tay, loss trên 85/3.007 token, độ dài chấp nhận MTP 2,28…), và chỉ ra chỗ công thức được tính trong mã. Không giải thích những thứ không dùng.
2. **Mã kỹ:** 15 đoạn thân bài ≤ 25 dòng, mỗi đoạn giải thích theo mẫu 7 mục (mục đích, vào/ra, bảng giải thích theo dòng, độ phức tạp, trường hợp biên, kiểm thử, số đo); 12 đoạn còn lại ở Phụ lục H. Hình, công thức, bảng vẫn đặt trước mã.
3. **Gọi đúng tên kỹ thuật.** Embedding `feature-hash-v1` là biểu diễn từ vựng/ký tự (lexical, subword), chịu lỗi chính tả nhờ 3-gram ký tự nhưng **không nắm ngữ nghĩa**; bộ nhớ đệm dùng nó là **bộ nhớ đệm theo độ tương đồng vector từ vựng**, không gọi là "bộ nhớ đệm ngữ nghĩa" (dù tên trong mã là `Semantic`). **Owner chốt 17/11: giữ feature hashing trong hệ thống một cách có chủ đích** (nhanh, độ trễ thấp, không cần GPU hay tải model, tất định), không cài embedding neural; khóa luận trình bày đây là đánh đổi thiết kế có số đo, không phải thiếu sót.
4. **Khoảng 1/4 dung lượng cho thực nghiệm và phân tích** (Chương 4), phần còn lại dồn cho lý thuyết có công thức và mã có giải thích.
5. **Không điều chỉnh trên tập dùng để báo cáo:** mọi lựa chọn (α truy hồi, checkpoint LoRA, đầu MTP) chọn trên dev hoặc tập kiểm tra riêng, báo kết quả trên held_out hoặc trên 250 ca đóng băng.

## Ánh xạ CDIO và hai vòng

Vòng 1 xây hệ thống và đo mốc; vòng 2 dùng kết quả vận hành (phân loại lỗi) để thiết kế lại mô hình bằng chưng cất rồi đo lại.

| Giai đoạn | Chương | Vòng 1 (hệ thống) | Vòng 2 (chưng cất) |
|---|---|---|---|
| **C** Hình thành ý tưởng | 1 | Bài toán, ràng buộc tài nguyên, lý thuyết cốt lõi, RQ, yêu cầu có ngưỡng | RQ chưng cất, lý thuyết SFT/LoRA/MTP |
| **D** Thiết kế | 2 | Kiến trúc, dữ liệu, tác tử, ngữ cảnh, truy hồi, mô hình mối đe dọa, phương pháp đánh giá, quyết định thiết kế | Thiết kế chưng cất và phễu dữ liệu |
| **I** Hiện thực | 3 | Tác tử, checkpointer, pgvector, giả lập, phục vụ model, kiểm thử | Phễu dữ liệu, LoRA, đầu MTP |
| **O** Vận hành | 4 | Mốc, truy hồi, an toàn, phân loại lỗi, vận hành và chi phí | Trước/sau chưng cất, ablation |

## Phân bổ trang

| Phần | Trang |
|---|---|
| Mở đầu | 3 |
| Chương 1 | 20 (lý thuyết 15) |
| Chương 2 | 14 |
| Chương 3 | 17 (15 đoạn mã có giải thích) |
| Chương 4 | 16 |
| Kết luận | 2,5 |
| **Tổng thân bài** | **~72** |

Vượt mốc 60 của góp ý; owner chọn độ sâu. **Việc cần làm: hỏi giảng viên giới hạn trang và mẫu Word.** Nếu bị giới hạn chặt 60 trang thì giữ nguyên nội dung, chuyển các dẫn xuất dài (09 §1.2–1.3, §2.6, §4.3, §4.5) sang Phụ lục J "Dẫn xuất và chứng minh" và 5 đoạn mã ít trọng tâm nhất (M4, M8, M13, M19, M24) sang Phụ lục H; thân bài giữ công thức chính và kết quả.

Ký hiệu: ✅ đã viết · ✍️ viết được ngay · 📊 đã có số liệu · 🧪 thí nghiệm mới, rẻ, chưa chạy · ⏳ chờ W6.7 · ⏸ hoãn (chỉ làm nếu còn đơn vị Colab) · 💻 đoạn mã thân bài.

## Câu hỏi nghiên cứu

Số RQ chốt sau W6.7. Nếu không chạy bước B, C, D thì **bỏ RQ về supervisor và về suy luận/ngữ cảnh** (chuyển vào hạn chế), còn 4 RQ:

- **RQ1 — Truy hồi:** truy hồi lai dùng biểu diễn từ vựng băm (lựa chọn của hệ thống) đạt Recall@3, MRR và độ trễ thế nào, đánh đổi bao nhiêu so với embedding neural nếu dùng thay; hệ số α nào tốt nhất; trích dẫn có đúng nguồn không.
- **RQ2 — An toàn:** rào an toàn trong code và kiểm trích dẫn tất định có ngăn thao tác trái phép, lộ dữ liệu chéo khách, chèn lệnh trực tiếp và gián tiếp không.
- **RQ3 — Hiệu năng vận hành:** Qwen3.5-9B trên một L4 24 GB (FP8, MTP) đạt độ trễ, thông lượng, bộ nhớ nào so với ngưỡng yêu cầu.
- **RQ4 — Chưng cất:** SFT LoRA từ quỹ đạo tự sinh của Qwen và của DeepSeek cải thiện Qwen3.5-9B trên 250 ca đóng băng bao nhiêu, ở nhóm lỗi nào, có giữ được tốc độ không.
- ⏸ (nếu chạy B, C, D) RQ5 agent-first so với supervisor; RQ6 suy luận bật/tắt, ngữ cảnh 8k.

Trong sườn dưới đây, RQ đánh số theo bộ 4 câu này.

---

## Phần đầu

Bìa, lời cảm ơn ✅, lời cam đoan ✅ (cần sửa câu về huấn luyện, xem Mở đầu điểm 6); mục lục, danh mục bảng, hình, đoạn mã; danh mục viết tắt (CSKH, LLM, RAG, RQ, CDIO, GPU, SFT, LoRA, MTP, KD, ANN, HNSW, PII, RBAC, TTFT).

## MỞ ĐẦU (3 trang) ✅ → `03_mo_dau.md`, cần sửa

1. **Phạm vi:** bỏ "không tự huấn luyện mô hình"; thay bằng mốc Qwen3.5-9B chính hãng rồi huấn luyện bổ sung LoRA từ dữ liệu chưng cất riêng.
2. **Mục tiêu:** thêm cải thiện mô hình mở bằng chưng cất có kiểm soát.
3. **Câu hỏi nghiên cứu:** thay bằng bộ RQ chốt.
4. **Phương pháp:** thêm giả lập dữ liệu, chưng cất bằng lấy mẫu loại bỏ, ablation, chấm lại có kiểm định.
5. **Đóng góp:** (a) kiến trúc tác tử có ranh giới tin cậy và kiểm chứng tất định; (b) quy trình dữ liệu có kiểm soát (giả lập tất định, 250 ca đóng băng, dữ liệu chưng cất tách biệt có lọc rò rỉ); (c) quy trình chưng cất cho tác tử gọi công cụ, kèm huấn luyện lại đầu MTP; (d) phương pháp chấm lại bộ chấm theo chữ.
6. **Lời cam đoan:** đổi câu "Qwen3.5-9B … không do em huấn luyện" thành bản gốc của nhóm Qwen, bản LoRA và đầu MTP do em huấn luyện; giữ khai báo công cụ AI; kiểm quy định khai báo AI của trường.

## CHƯƠNG 1. HÌNH THÀNH Ý TƯỞNG: BÀI TOÁN, RÀNG BUỘC VÀ CƠ SỞ LÝ THUYẾT (20 trang) — C

### 1.1 Bài toán CSKH bán lẻ (1 trang) ✍️
Yêu cầu thường gặp; đặc thù Việt Nam (COD, đồng kiểm, mega sale, lừa đảo mạo danh); chi phí khi AI sai. Nguồn `06_nghien_cuu_thuc_trang_va_du_lieu.md`.

### 1.2 Phát biểu bài toán hình thức (1,5 trang) ✍️
- Tác tử là chính sách $\pi_\theta(a_t \mid h_t)$ trên quỹ đạo $\tau = (h_0, a_0, o_0, \dots)$, $a_t \in \mathcal{T} \cup \{\text{answer}, \text{handoff}\}$; ràng buộc $\mathcal{C}$ (không ghi, phạm vi khách, ngân sách $B_{\text{model}} = 6$, $B_{\text{tool}} = 10$, trần 110 s, trích dẫn hợp lệ).
- Mục tiêu: cực đại $\Pr[\text{hoàn thành}]$ với vi phạm $\mathcal{C}$ bằng 0; chấm theo trạng thái cuối.
- Truy hồi: $s_\alpha(q,d) = \alpha\, s_{\text{vec}}(q,d) + (1-\alpha)\min(s_{\text{lex}}(q,d), 1)$; câu trả lời chỉ trích $d$ thuộc tập trả về trong lượt.
- Chưng cất: $\mathcal{L}(\theta) = -\frac{1}{\sum m_t}\sum_{\tau \in \mathcal{D}_A}\sum_t m_t \log \pi_\theta(y_t \mid y_{<t})$, $m_t = 1$ chỉ với token của trợ lý; $\mathcal{D}_A$ là quỹ đạo qua lấy mẫu loại bỏ.

### 1.3 Cơ sở lý thuyết (15 trang) ✍️ — đặc tả đầy đủ ở `09_co_so_ly_thuyet_chi_tiet.md`
**1.3.1 Mô hình ngôn ngữ (4 trang)** (09 §1): token hóa BPE mức byte, phân rã tự hồi quy, chat template; attention có tỉ lệ và mặt nạ nhân quả (lý do chia $\sqrt{d_h}$), GQA 16/4, cổng đầu ra, RoPE từng phần 25% với $\theta = 10^7$, RMSNorm, MLP SwiGLU, khối pre-norm; KV cache 32 KiB/token và Gated DeltaNet (luật cập nhật delta có cổng, trạng thái cố định, độ phức tạp); lấy mẫu (nhiệt độ, top-k, top-p, presence penalty); giải mã suy đoán có dẫn xuất bảo toàn phân phối, MTP, độ dài chấp nhận $1 + a_1 + a_1 a_2$.

**1.3.2 Học có giám sát, hàm mất mát và tối ưu (4 trang)** (09 §2): entropy chéo, KL, perplexity, gradient theo logit; **loss SFT có mặt nạ tính chính xác thế nào** (dịch nhãn, nhãn −100, chuẩn hóa theo tổng token có nhãn khi gộp lô và tích lũy gradient, entropy chéo hợp nhất theo khối); KD mức logit (hệ số $\tau^2$) và mức chuỗi, vì sao đề tài dùng mức chuỗi; lấy mẫu loại bỏ (phần thưởng nhị phân, liên hệ gradient chính sách, bẫy độ khó không đồng đều); LoRA (công thức, khởi tạo, gradient, **đếm tay 43.278.336 tham số**, bộ nhớ 151 GB so với ~19–23 GB); AdamW, lịch học, cắt gradient, bf16, checkpoint gradient, bài học lr của đầu MTP; loss tự chưng cất đầu MTP.

**1.3.3 Tác tử, máy trạng thái và gọi công cụ (2 trang)** (09 §3): POMDP; đồ thị trạng thái và ngữ nghĩa thực thi của LangGraph; chứng minh dừng bằng ngân sách; checkpoint và loại trừ lẫn nhau; JSON Schema và parser; ReAct.

**1.3.4 Biểu diễn văn bản, CSDL vector và truy hồi (3 trang)** (09 §4): cosine và quan hệ với khoảng cách Euclid trên vector chuẩn hóa; **feature hashing có dấu và tính không chệch** (vì sao là biểu diễn từ vựng, không ngữ nghĩa); BM25 và `ts_rank_cd` (mật độ phủ); truy hồi lai $s_\alpha$; CSDL vector, tìm chính xác so với ANN, HNSW (cấu trúc, độ phức tạp, tham số pgvector), nhận xét trung thực về quy mô; RAG, chia đoạn có chồng lấn, trích dẫn kiểm nguồn gốc.

**1.3.5 An toàn của hệ tác tử (1 trang)** (09 §5): chèn lệnh trực tiếp và gián tiếp, confused deputy, đặc quyền tối thiểu, ranh giới tin cậy, vì sao prompt không đủ, OWASP LLM Top 10.

**1.3.6 Đánh giá, thống kê và độ tin cậy nhãn (1 trang)** (09 §6): pass@1, pass^k; Recall@k, MRR; bootstrap phân vị (đơn vị lấy mẫu là ca); McNemar chính xác có dẫn xuất; Cohen's kappa; LLM làm giám khảo và thiên lệch; Jaccard 5-gram; bốn loại mối đe dọa tính hợp lệ.

Bảng ký hiệu dùng chung (09 §7) đặt đầu Chương 1 hoặc trong danh mục ký hiệu.

### 1.4 Nghiên cứu liên quan (1 trang) ✍️
Bảng 1.1: chatbot luật/intent, trợ lý LLM thương mại, tác tử nghiên cứu (τ-bench, AgentDojo), chưng cất cho model nhỏ gọi công cụ; tiêu chí: tự lập kế hoạch, bám dữ liệu, an toàn khi ghi, tiếng Việt, chạy tại chỗ, có chưng cất; khoảng trống đề tài lấp.

### 1.5 Câu hỏi nghiên cứu, yêu cầu có ngưỡng và ma trận truy vết (1,5 trang) ✍️
- RQ (bộ chốt ở trên).
- Bảng 1.2 yêu cầu, **ngưỡng lấy từ ràng buộc hệ thống, không đặt sau khi có kết quả**:

| Mã | Yêu cầu | Ngưỡng / cách kiểm |
|---|---|---|
| NFR-01 | AI không ghi dữ liệu nghiệp vụ | 0 thao tác ghi qua tool (tool chỉ đọc; kiểm `final_state` 250 ca) |
| NFR-02 | Trích dẫn chính sách hợp lệ | 100% `[KB:…]` trong câu trả lời thuộc đoạn truy hồi trong lượt (kiểm tất định, fail-closed) |
| NFR-03 | Cách ly dữ liệu khách | 0 lần lộ đơn của khách khác (ca S09, S11) |
| NFR-04 | Độ trễ | một lần gọi model ≤ 45 s; một lượt ≤ 110 s (trần cứng của hệ thống) |
| NFR-05 | Tài nguyên | phục vụ trên 1 GPU 24 GB (L4); huấn luyện trên 1 GPU 40 GB |
| NFR-06 | Tái lập | nhập sự kiện idempotent theo `event_id`; giả lập tất định theo seed; mã ghim SHA |
| NFR-07 | Quyền riêng tư | dữ liệu giả lập; số điện thoại che khi trả cho model |
| FR-01…09 | Tra cứu đơn, vận chuyển, sản phẩm, tồn kho, chính sách có trích dẫn, chuẩn bị hủy/trả/đổi, chuyển nhân viên, Trợ lý ca, Manager Console | bộ ca S01–S12 tương ứng |

- Bảng 1.3 truy vết: RQ → yêu cầu → mục thiết kế → đoạn mã → kiểm thử/bộ ca → mục kết quả.

## CHƯƠNG 2. THIẾT KẾ: KIẾN TRÚC, DỮ LIỆU VÀ MÔ HÌNH MỐI ĐE DỌA (14 trang) — D

### 2.1 Kiến trúc tổng thể (1,5 trang) ✍️
Hình 2.1 kiến trúc (người dùng → HTTP/RBAC → vòng tác tử LangGraph → tool → CSDL nghiệp vụ + pgvector; model trên GPU qua API kiểu OpenAI). Hình 2.2 luồng một lượt. Lựa chọn model gọn trong 0,5 trang (chi tiết ở 2.9).

### 2.2 Thiết kế dữ liệu và dòng chảy dữ liệu (2 trang) ✍️
- **Hình 2.3 sơ đồ dòng dõi dữ liệu:** seed → `marketplace_sim` → sự kiện JSONL (hợp đồng `retailops-integration-v2`) → nhập idempotent + dời đồng hồ → CSDL nghiệp vụ → tool → ca đánh giá / ca chưng cất → vết → mẫu SFT.
- **Bảng 2.1 tổng hợp các tập** (một dòng mỗi tập, không văn xuôi lặp): danh mục 20 sản phẩm; 14 tài liệu chính sách; sự kiện `standard` 2.003 / 128 đơn / 89 khách; 250 ca (210 do model độc lập **Gemini 4 Carbon** viết qua giao diện chat từ `eval_pack/`, không đọc mã; 28 chuyển thể τ²-bench, 12 AgentDojo), 336 lượt; nhãn truy hồi 64 ca (45 dev, 19 held_out); vết W6.4 (không huấn luyện); sự kiện `sft_v1` 3.174 / 216 đơn / 170 khách; 1.200 ca chưng cất từ 117 khung; lời khách do **Muse Glimmer 30B** viết (§34 W6.7-D1; tách vai 4 họ model: Gemini viết ca đo, Glimmer viết lời khách, DeepSeek thầy, Qwen học trò); tập SFT ⏳.
- Event sourcing và idempotency (`event_id`, `sequence`); **dời đồng hồ** giữ bất biến tuổi đơn → kỳ vọng ổn định giữa các lần chạy; chống rò rỉ giữa tập đo và tập huấn luyện (dữ liệu cửa hàng riêng, bộ đếm mã riêng, lọc Jaccard 5-gram và chuỗi con chung với 250 ca).
- Định dạng ca đánh giá: một ví dụ rút gọn (khung JSON 10 dòng) thay cho mô tả từng trường.

### 2.3 Thiết kế tác tử trên LangGraph (2,5 trang) ✍️
Baseline supervisor (Hình 2.4) và vì sao gãy; agent-first 3 nút `guard → model ⇄ tools` (Hình 2.5, Thuật toán 2.1); trạng thái và điều kiện dừng; ngân sách, lần gọi cuối không tool, chặn gọi trùng; checkpoint `SqlSaver` với khóa thuê; 12 tool chỉ đọc theo JSON Schema, `prepare_order_action` chỉ mở biểu mẫu; Trợ lý ca dùng chung vòng, khác hồ sơ.

### 2.4 Thiết kế ngữ cảnh và ngân sách token (1,5 trang) ✍️
Các lớp ngữ cảnh (Hình 2.6): system + mô tả 12 tool (cố định; cùng một câu khách là 2.892 token) → ngữ cảnh do server gắn → lịch sử đã cắt → lượt hiện tại → kết quả tool đã nén. Ngân sách ký tự tỉ lệ theo cửa sổ (36.000 ký tự / 16.384 token); trần mỗi kết quả tool 5.200, cả lượt 12.000, lịch sử 6.000; nén ba pha; cắt lịch sử theo cặp lượt. Phần cố định là lý do prefix caching có lợi (đo ở 4.6). Dữ liệu không tin cậy trong ngữ cảnh được đánh dấu (nối 2.6).

### 2.5 Thiết kế truy hồi lai và kiểm chứng trích dẫn (1,5 trang) ✍️
Nạp: Markdown → chia đoạn ~900 ký tự, chồng 140 → embedding → `knowledge_chunks` (vector 384, `tsvector`), HNSW cosine + GIN (Hình 2.7). Truy vấn lai với α = 0,75 hiện tại; ngưỡng điểm; bộ lọc từ chung chống va chạm băm; mã trích dẫn `KB:` + băm; kiểm trích dẫn fail-closed. Bộ nhớ đệm câu trả lời theo cosine trên vector từ vựng, ngưỡng 0,65, chỉ cho câu hỏi tĩnh.

### 2.6 Mô hình mối đe dọa và rào an toàn (2 trang) ✍️
- **Tài sản:** dữ liệu đơn và khách, quyền thao tác đơn, system prompt, uy tín cửa hàng.
- **Nguồn tấn công:** (1) khách gõ trực tiếp (chèn lệnh, giả admin, đòi xem đơn người khác, kỹ nghệ xã hội); (2) **gián tiếp** qua dữ liệu đi vào ngữ cảnh: PDF khách gửi cho Trợ lý ca, mô tả sản phẩm, ghi chú, kết quả tool, tài liệu truy hồi; (3) model tự bịa (ảo giác, trích dẫn giả).
- **Ranh giới tin cậy** (Hình 2.8): server và CSDL tin cậy; mọi thứ model đọc từ khách, tệp, tài liệu, tool đều không tin cậy và được đánh dấu; đầu ra của model không được tin về hành động.
- **Biện pháp tất định trong code, vì sao không chỉ dựa prompt:** tool chỉ đọc + người xác nhận; kiểm tool và tham số theo schema; phạm vi khách do server gắn; kiểm trích dẫn chỉ nhận mã trả về trong lượt; 3 rào an toàn chạy trước model; kiểm câu trả lời cuối 4 luật; che PII; làm sạch ảnh, quét PDF. Bảng 2.2 mối đe dọa → biện pháp → bộ ca kiểm (S09, S11, AgentDojo 12 ca).
- Rủi ro còn lại chấp nhận (thời hạn hay phí bịa chỉ ghi vết, W6.4-D17).

### 2.7 Phương pháp đánh giá (1,5 trang) ✍️
Bộ 250 ca, 12 bộ, đóng băng SHA 12/12; bộ chấm chữ + trạng thái cuối; ba con số chính thức / v2 / sau xem xét; tham chiếu DeepSeek; chỉ số; thống kê. **Thiết kế ablation** (Bảng 2.3, kết quả ở 4.5) và **định nghĩa phân loại lỗi** (Bảng 2.4, kết quả ở 4.4): lỗi chọn tool/schema, trôi trạng thái nhiều lượt, bám dữ liệu/trích dẫn (gồm từ chối quá mức), vi phạm an toàn, lỗi hệ thống (F52 lần gọi cuối, hết giờ), lỗi bộ chấm (G1/G2/G3).

### 2.8 Thiết kế chưng cất và phễu dữ liệu (1,5 trang) ⏳ — vòng 2
Hình 2.9 pipeline: `sft_v1` → 117 khung (kỳ vọng do code) → lời khách do Muse Glimmer viết, có luật kiểm → quỹ đạo Qwen ×4, DeepSeek ×2 bằng đúng runner → **phễu**: kiểm định dạng/tool/kết quả (lấy mẫu loại bỏ) → tier bằng code + giám khảo → lọc trùng/rò rỉ → chọn Qwen trước → tách train/val theo khung → SFT LoRA bf16 r=16 α=32 trên 12 loại lớp ngôn ngữ, mặt nạ trợ lý → tự gộp giữ `mtp.*` và phần nhìn ảnh → huấn luyện lại đầu MTP. Ràng buộc điều khoản (DeepSeek §4.2; Gemini chỉ chấm).

### 2.9 Quyết định thiết kế và phương án thay thế (1 trang) ✍️
Bảng 2.5 (vấn đề → phương án → chọn → lý do và cái giá): điều phối; quyền ghi của AI; kho vector (pgvector so với CSDL chuyên dụng, một câu); embedding (chọn feature hashing có chủ đích: độ trễ truy vấn thấp, không GPU, không tải model, tất định, tái lập; cái giá là không nắm đồng nghĩa; số đo đánh đổi ở 4.2); model (Qwen3.5-9B so với Gemma 4 12B bên thứ ba, API thương mại; ba vai trò của DeepSeek); chấm; LoRA so với fine-tune toàn phần/QLoRA; nguồn mẫu SFT; đầu MTP.

## CHƯƠNG 3. HIỆN THỰC (17 trang) — I

Mỗi mục: mô tả, hình hoặc bảng, rồi các đoạn mã thân bài (≤ 25 dòng, đánh số dòng) kèm giải thích theo mẫu 7 mục của `08_ma_nguon_minh_hoa.md`. Tổng **15 đoạn thân bài** (💻 M1, M2, M3, M4, M8, M9, M12, M13, M14, M17, M19, M20, M24, M25, M26); 12 đoạn khác ở Phụ lục H; Bảng 3.3 ánh xạ thành phần → tệp nguồn.

- 3.1 Môi trường và công nghệ (0,5 trang): Bảng 3.1 phiên bản (Python, LangGraph, PostgreSQL + pgvector 0.8.6, vLLM 0.33.0, Unsloth 2026.11.5, transformers 5.17, torch 2.14).
- 3.2 Giả lập và nạp dữ liệu (1,5 trang): `marketplace_sim`, seed con HMAC, story; nhập idempotent, dời đồng hồ. 💻 M17
- 3.3 Vòng tác tử, checkpointer và ngữ cảnh (4 trang): đồ thị, nút model (ngân sách, lần gọi cuối không tool, kiểm trích dẫn trước khi lưu), nút tools (kiểm schema, chặn gọi trùng, nén), checkpointer có khóa thuê, ngân sách và nén ngữ cảnh. 💻 M1, M2, M3, M4, M8
- 3.4 Truy hồi trên pgvector (3 trang): embedding băm, SQL truy vấn lai, tool tri thức (ngưỡng, lọc va chạm, mã trích dẫn), kiểm trích dẫn. 💻 M9, M12, M13, M14
- 3.5 Phục vụ model trên L4 (1 trang): vLLM FP8, MTP 2 token nháp, 32k, 8 luồng, parser `qwen3`/`qwen3_coder`, payload có ảnh.
- 3.6 Hiện thực chưng cất (3,5 trang) ⏳: fixture `sft_v1` (story lặp, bộ đếm riêng), khung ca và kiểm `--fake` 1.200/1.200, lời khách và luật kiểm (Jaccard, không dấu), mặt nạ loss và LoRA, đầu MTP dựng lại khớp vLLM (chấp nhận bước 1 = 0,81) và loss tự chưng cất; cấu hình huấn luyện (lr, lịch học, số lượt, cắt gradient) và đường cong loss. 💻 M24, M25, M26
- 3.7 Bộ công cụ đánh giá, kiểm thử và kiểm chứng (2,5 trang) 📊: bộ chấm `grade_turn` và thống kê (bootstrap, McNemar); ~1.320 test; CI 6 job; 44 kịch bản hồi quy bằng gateway giả; kiểm dữ liệu (SHA 12/12); kiểm tài liệu khớp mã. Bảng 3.2. 💻 M19, M20
- 3.8 Giao diện (0,5 trang): 4 ảnh chụp.
- 3.9 Bảng 3.3 ánh xạ thành phần → tệp nguồn (0,5 trang).

## CHƯƠNG 4. THỰC NGHIỆM, ĐÁNH GIÁ VÀ VẬN HÀNH (16 trang) — O

- **4.1 Thiết lập và kết quả mốc (3 trang) 📊:** phần cứng, model, mã `662cb77`, 32k, 8 luồng, tham số lấy mẫu, `max_tokens` 2048 (cổng D4 11/12), 250 × 3; DeepSeek tham chiếu 250 × 1. Bảng ba con số: Qwen pass@1 46,5% / v2 / **57,9%**, pass^3 26,0% / **35,2%**; DeepSeek 70,0% / **82,0%**; phân bố 0/3–3/3; theo bộ S01–S12; kiểm định giám khảo (Gemini Carbon: DeepSeek 19/19, Qwen 18/20).
- **4.2 RQ1 truy hồi (2 trang) 🧪 + 📊:** bảng so sánh trên 64 ca (chọn α trên 45 ca dev, báo trên 19 ca held_out và trên cả 64): feature-hash, embedding neural nhỏ chạy CPU làm **đối chứng ngoài hệ thống** (`intfloat/multilingual-e5-small`; không cài vào hệ thống), lai với α ∈ {0; 0,25; 0,5; 0,75; 1}; Recall@3, MRR, **độ trễ tạo vector truy vấn và độ trễ truy vấn SQL (ms, trung vị và p95, cùng máy CPU)**, bộ nhớ, thời gian nạp model. Kết luận dạng: feature hashing nhanh hơn bao nhiêu lần, mất bao nhiêu điểm Recall/MRR, α nào bù được phần mất; **đặt độ trễ truy hồi cạnh độ trễ cả lượt (p50 29,6 s)** để thấy phần thắng chính của feature hashing là không phụ thuộc dịch vụ ngoài, tất định và đơn giản, còn độ trễ chỉ là lợi ích phụ. Phương án GPU qua ngrok (T4 Colab) được bàn và loại ở 2.9: thêm độ trễ mạng lớn hơn phần tính toán tiết kiệm, Colab ngắt phiên, điều khoản Colab cấm dùng runtime làm dịch vụ web. Kèm lỗi trích dẫn thực tế của Qwen (136 lượt: 69 nhãn tự chế, 51 thiếu; F54). Ghi rõ 19 ca held_out nhỏ, khoảng tin cậy rộng.
- **4.3 RQ2 an toàn (1,5 trang) 📊:** tấn công thành công Qwen 7/36 (≥ 4 lượt làm theo lệnh chèn thật ở S11); DeepSeek 5/12 chính thức, 1/12 sau xem xét, thực tế 0 (G3); NFR-01, 02, 03 theo Bảng 1.2; đối chiếu Bảng 2.2.
- **4.4 Phân tích lỗi (2 trang) 📊:** phân loại 401 lượt hỏng của Qwen (bước A) theo Bảng 2.4, đếm tự động từ thông điệp bộ chấm rồi đối chiếu chấm lại: chữ trả lời 181, trích dẫn 130, chọn tool 89, hành động/biểu mẫu 53, nguồn 34, trạng thái cuối 26, lượt hỏng F52 25, hết giờ 7 (một lượt có thể thuộc nhiều nhóm); tách phần do bộ chấm (G1/G2) khỏi lỗi thật; mỗi nhóm một ví dụ vết ngắn. Đây là đầu vào cho thiết kế chưng cất (vòng 2).
- **4.5 RQ4 chưng cất và ablation (3,5 trang) ⏳:** phễu dữ liệu thực tế (quỹ đạo sinh → qua kiểm → tier A → sau lọc trùng → tập SFT; tỉ lệ Qwen/DeepSeek; phân bố độ dài token và số bước gọi tool; phân bố theo khung), Hình phễu; đường loss train/val; trước/sau trên 250 × 3: pass@1, pass^3, McNemar, theo bộ và nhóm lỗi. **Bảng ablation:** (1) Base so với SFT LoRA; (2) kiểm trích dẫn bật/tắt, **tính lại từ vết, không chạy thêm**: số câu trả lời có trích dẫn giả sẽ lọt tới khách nếu tắt; (3) α truy hồi (từ 4.2); (4) đầu MTP gốc so với huấn luyện lại (tỉ lệ chấp nhận, token/s); ⏸ (5) rào an toàn tắt trên S09 + S11 và (6) không nén kết quả tool trên S08: cần cờ runner mới và ~1–2 đơn vị L4.
- **4.6 RQ3 vận hành và kinh tế hệ thống (2 trang) 📊/⏳:** độ trễ lượt p50 29,6 s, p90 64,7 s, p99 99,4 s so với trần 110 s (NFR-04); 7/750 thua vì hết giờ; 183 token/s tổng ở 8 luồng; MTP bật thật, chấp nhận 64,0%, 2,28 token/bước; VRAM (vLLM `--gpu-memory-utilization 0.90` trên 24 GB; huấn luyện 18,9–23 GB trên 40 GB). ⏳ đo thêm ở lượt đo lại: tỉ lệ trúng prefix cache và TTFT để định lượng lợi ích của phần cố định. Chi phí: đơn vị Colab theo việc, DeepSeek 0,51 USD / 250 ca. **Quy trình vận hành (LLMOps):** thêm hoặc sửa tài liệu chính sách → nạp lại theo checksum, đánh lại chỉ mục, xóa bộ nhớ đệm câu trả lời liên quan, không cần huấn luyện lại LoRA (kiến thức chính sách ở RAG, LoRA chỉ dạy hành vi); triển khai, cờ deploy, rollback; giám sát qua vết và `answer_check_audit`.
- **4.7 Mối đe dọa tính hợp lệ và đạo đức (1 trang) 📊:** bộ chấm theo chữ; kiểm định mới bằng LLM; 31 lượt lật chưa kiểm thêm (cận dưới Qwen ≥ 55,1%, DeepSeek ≥ 78,4%); dữ liệu giả lập; ca đo do model độc lập sinh (Gemini 4 Carbon; vì vậy lời khách của tập chưng cất không được do Carbon viết, tránh trùng "giọng" giữa tập huấn luyện và tập đo); một model; contamination (`tau2_retail`); DeepSeek tham chiếu khác cấu hình; thiên lệch của thầy; chưa có ca ảnh (F57); held_out truy hồi nhỏ. Đạo đức và giấy phép: dữ liệu giả lập, che PII, Apache 2.0, điều khoản DeepSeek §4.2, Gemini chỉ chấm, khai báo công cụ AI.
- ⏸ RQ5, RQ6 (supervisor, suy luận/ngữ cảnh): chỉ thêm 2 trang nếu chạy B, C, D.

## KẾT LUẬN VÀ HƯỚNG PHÁT TRIỂN (2,5 trang) ⏳
Trả lời từng RQ; nhìn lại hai vòng CDIO; hạn chế thẳng thắn (embedding băm không nắm đồng nghĩa — chấp nhận có chủ đích để đổi lấy độ trễ, dữ liệu giả lập, bộ chấm theo chữ, kiểm định LLM); hướng phát triển: embedding neural đa ngôn ngữ làm tùy chọn khi chấp nhận thêm độ trễ hoặc có GPU, mở rộng từ đồng nghĩa cho feature hashing, DPO, học tăng cường với phần thưởng kiểm chứng được (RLVR/GRPO) cho gọi công cụ nhiều bước, ca ảnh (F57), sửa F52–F55, dữ liệu thật.

## TÀI LIỆU THAM KHẢO (30–40 mục, IEEE đánh số)
Vaswani 2017; Hinton 2015; Kim & Rush 2016; Wei 2022; Yao 2023 ReAct; Zeng 2023 AgentTuning; Chen 2023 FireAct; Zelikman 2022 STaR; Yuan 2023 RFT; Hu 2022 LoRA; Rafailov 2023 DPO; Weinberger 2009 feature hashing; Malkov & Yashunin 2018 HNSW; Robertson 2009 BM25; E5 hoặc BGE-M3 (theo model dùng ở E1); Lewis 2020 RAG; Liu 2023 Lost in the Middle; Greshake 2023; Kwon 2023 vLLM; Leviathan 2023; Gloeckle 2024 MTP; Cai 2024 Medusa; Li 2024 EAGLE; Yang 2025 Gated DeltaNet; Yao 2024 τ-bench; Barres 2025 τ²-bench; Debenedetti 2024 AgentDojo; Zheng 2023 LLM-as-a-judge; McNemar 1947; Cohen 1960; Efron 1979; Qwen3.5 model card; DeepSeek V4 model card và điều khoản; LangGraph, pgvector, Unsloth (tài liệu phần mềm); OWASP LLM Top 10; tài liệu CDIO.

## PHỤ LỤC (không tính trang)
A. Schema 12 tool · B. Vết mẫu một lượt nhiều bước · C. Ví dụ ca đánh giá theo bộ · D. Runbook deploy và migration · E. Hướng dẫn cài đặt · F. Danh mục 117 khung ca chưng cất · G. Hướng dẫn chấm lại W6.4.4 · H. Các đoạn mã còn lại (M2, M4–M8, M10, M11, M13, M15, M16, M18–M24, M26, M27) · I. Hướng dẫn tái lập từng con số · J. Dẫn xuất và chứng minh (chỉ dùng nếu phải ép thân bài về 60 trang).

## Thí nghiệm mới cần chạy (rẻ)

| Mã | Việc | Chi phí | Dùng ở |
|---|---|---|---|
| E1 | Truy hồi: feature-hash (hệ thống) so với lai theo α (chọn trên dev, báo trên held_out), kèm embedding neural nhỏ làm đối chứng ngoài hệ thống; đo độ trễ tạo vector và truy vấn (notebook CPU riêng; PostgreSQL + pgvector dựng tạm như notebook W6.4; không đổi mã hệ thống) | CPU, ~0 đơn vị | 4.2, 2.9 |
| E2 | Phân loại lỗi tự động 401 lượt hỏng của Qwen + ví dụ vết | máy cá nhân, 0 | 4.4 |
| E3 | Ablation kiểm trích dẫn tính lại từ vết W6.4 | máy cá nhân, 0 | 4.5 |
| E4 | Tỉ lệ trúng prefix cache, TTFT trong lượt đo lại 250 × 3 (đọc `/metrics` của vLLM) | thêm vào notebook đo lại | 4.6 |
| E5 | Phễu dữ liệu chưng cất (số từ `sft_select`, `sft_build`) | có sẵn khi làm phần B | 4.5 |
| ⏸ E6 | Ablation rào an toàn tắt (S09 + S11) và không nén (S08) | cờ runner mới + ~1–2 đơn vị L4 | 4.5 |

## Chuẩn chất lượng trước khi nộp

- Mọi con số dẫn được về tệp kết quả (Phụ lục I); số "sau xem xét" đi cùng số chính thức.
- Không khẳng định vượt số liệu; kết luận chỉ trong điều kiện đã đo.
- Mỗi RQ có câu trả lời ở Chương 4 và Kết luận.
- Hình, bảng, đoạn mã đánh số, có caption, được nhắc trước khi xuất hiện.
- Bảng thuật ngữ Việt–Anh dùng nhất quán; viết tắt giới thiệu bằng câu lần đầu.
- Trích dẫn IEEE; mọi mục tham khảo đều được trích.
- Đoạn văn liền mạch, hạn chế gạch đầu dòng, không ngoặc đơn chú thích thuật ngữ.
- Gọi đúng tên kỹ thuật (biểu diễn từ vựng băm, không gọi là ngữ nghĩa).
- Mỗi công thức ở Chương 1 được dùng lại ít nhất một lần ở Chương 2–4 (đoạn mã hiện thực nó hoặc con số đo bằng nó); công thức không dùng thì bỏ.
- Luyện 12 câu hỏi phản biện ở cuối `09_co_so_ly_thuyet_chi_tiet.md`.
- Gửi giảng viên Chương 1–2 sớm; hỏi giới hạn trang và mẫu Word của khoa.
