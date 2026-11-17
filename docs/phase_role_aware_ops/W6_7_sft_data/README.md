# W6.7 — Chưng cất Qwen3.5-9B bằng SFT: KẾ HOẠCH CHỐT (2026-11-16)

Mốc trước SFT (W6.4, sau chấm lại W6.4.4, hiệu chỉnh theo kiểm định Gemini Carbon): Qwen pass@1 46,5% chính thức / 57,9% sau xem xét, pass^3 26,0% / 35,2%; DeepSeek tham chiếu 70,0% / 82,0%. Báo cáo: `../W6_4_measurement/`.

## 1. Quyết định đã chốt

| # | Quyết định | Ghi chú |
|---|---|---|
| 1 | **250 ca `evals/suites` chỉ để đo** | Không vào huấn luyện, kể cả diễn đạt lại; từ W6.4 chỉ mang sang nhóm lỗi |
| 2 | **Chỉ SFT**, LoRA bf16 Unsloth | Không continued pre-training; DPO/tự chưng cất có gợi ý là tùy chọn sau khóa luận |
| 3 | **Thầy = DeepSeek V4.1 Flash** (`deepseek-flash`) | ToS DeepSeek §4.2 cho phép distillation; chạy ngoài giờ cao điểm (trước 13:00, sau 17:00, cuối tuần) |
| 4 | **Nguồn mẫu: trộn, ưu tiên Qwen** | Ca có lượt Qwen đạt tier A → lấy lượt tốt nhất của Qwen; ca không có → lượt tier A của DeepSeek |
| 5 | **Gemini chỉ chấm, xếp tier A/B/C** | Không viết lại suy luận làm dữ liệu huấn luyện (điều khoản Gemini + suy luận viết lại không được kiểm chứng) |
| 6 | **1.200 ca chất lượng cực cao** | 80–120 khung ca (10–15 ca/khung), chỉ tier A, thử 100 ca trước |
| 7 | **Khớp hoàn toàn hệ thống hiện tại** | Sinh mẫu bằng đúng runner của bộ đo; dựng SFT từ request ghi trong vết; đóng băng mã hệ thống của mốc W6.4 (`retailops/`, `agent_protocol.py`, `retailops_providers.py`, `data/` không đổi từ `662cb77`); W6.5 sửa sau |
| 8 | **Qwen chạy 4 lần mỗi ca, DeepSeek 2 lần** | k=4: ca đạt ~1/3 có 80% cơ hội có mẫu, ca đạt ~2/3 có 99% |
| 9 | **Sinh dữ liệu Qwen trên A100 40 GB** | fp8 (W8A16) + MTP như lúc đo, `--max-num-seqs` 32, 24–32 runner; đợt thử đo 16/24/32 luồng rồi chốt. Không dùng A100 80 GB (cùng sức tính, đắt hơn 32%) |
| 10 | **Huấn luyện A100 40 GB; đo lại 250 ca × 3 trên L4** | 80 GB chỉ khi p95 độ dài chuỗi SFT vượt ~16 nghìn token |
| 11 | **Dữ liệu cửa hàng riêng `sft_v1`** | `marketplace_sim` seed 20261201 (mặc định 20261106) → `data/demo_events/store_events_sft_v1.jsonl`; runner nạp theo `fixture` |
| 12 | **Lời khách do Muse Glimmer 30B viết** (owner chốt 2026-11-17, §34 W6.7-D1) | Meta, trọng số Apache 2.0, chính sách sử dụng không cấm dùng đầu ra để huấn luyện; tự chạy bản FP8 trên **Colab A100 40 GB** bằng vLLM (`--tool-call-parser muse_glimmer --reasoning-parser muse_glimmer`, `Reasoning strength: low`); mỗi câu gắn nhãn người viết (chính sách mục 3.5: không trình bày đầu ra như do người viết). Tách vai 4 họ model: Gemini Carbon viết 210 ca đo, Glimmer viết lời khách, DeepSeek làm thầy, Qwen học. DeepSeek đối chứng ở đợt thử và viết thay phiếu Glimmer từ chối |

## 2. Định dạng một ca

Giống hệt `evals/suites/S*.jsonl` (một dòng JSON): `id` (bắt đầu bằng `t`), `category`, `title`, `fixture: "sft_v1"`, `customer`, `meta` (`suite` T01–T12, `split: "train"`, `style`, `origin: "sinh_sft"`, `template`, `source_note`), `knowledge`, `turns[]` (`user`, `expect`), `final_state`; Trợ lý ca thêm `actor`, `case_setup`, `mode`. `expect` và `final_state` **do code sinh** từ khung ca, dùng lại nguyên bộ chấm hiện có để lọc lượt đạt.

## 3. Quy trình

| Bước | Việc | Ai | Máy |
|---|---|---|---|
| 1 | Fixture `sft_v1` + runner nạp fixture theo tên | code | máy owner |
| 2 | 80–120 khung ca → 1.200 ca (`expect`, `final_state`) + phiếu yêu cầu lời khách (ý định, dữ kiện được nhắc, giọng) | code | máy owner |
| 3 | Viết lời khách (1.406 phiếu, gồm các lượt sau và tin nhắn Trợ lý ca) → code kiểm (đúng mã đơn, không lộ đáp án, độ giống với 250 ca dưới ngưỡng) | **Muse Glimmer 30B** (FP8, vLLM cục bộ); DeepSeek viết thay phiếu bị từ chối | Colab A100 40 GB (~2–4 đơn vị) |
| 4a | Qwen ×4, `--trace-out` | runner | Colab A100 40 GB |
| 4b | DeepSeek ×2, `--trace-out` (song song 4a) | runner | Colab CPU |
| 5 | Xếp tier: code lọc (đạt chính thức + v2, không cờ `answer_check`/audit, không tool trùng, ít tool) → chọn 1–2 ứng viên/ca → Gemini Hydrogen chấm tính nhất quán suy luận–hành động và không bịa (gói ẩn danh, hai nhóm, trích dẫn code kiểm) → tier A/B/C | code + Hydrogen | máy owner |
| 6 | Dựng tập SFT: lượt tier A → hội thoại chat template Qwen3.5 + tool `qwen3_coder` (giữ suy luận của lượt được chọn; mẫu DeepSeek giữ phần suy luận, ghi tỉ lệ); tách train/val theo khung | code | máy owner |
| 7 | Huấn luyện LoRA: thử 50–100 mẫu đo token/s, rồi 2–3 epoch; gắn LoRA mọi lớp tuyến tính | Unsloth | Colab A100 40 GB |
| 8 | Đo lại 250 ca × 3 (notebook W6.4, model đã gộp LoRA, cùng cấu hình) → chấm lại W6.4.4 → McNemar so mốc; kiểm MTP sau LoRA | runner + `eval_regrade.py` | Colab L4 |

Toàn bộ bước 2–6 chạy **thử 100 ca** trước; owner xem tay một mẫu nhỏ; đạt mới sinh đủ.

## 4. Phân bổ 1.200 ca

| Nhóm | Lỗi W6.4 nhắm tới | Ca |
|---|---|---|
| T01–T03 tra cứu đơn, sản phẩm, chính sách có trích dẫn | Trích dẫn sai/thiếu (136 lượt Qwen) | 300 |
| T04–T06 hủy/đổi/trả nhiều bước kiểu τ² | S04–S06 yếu, mở biểu mẫu sai | 300 |
| T08 đa lượt, đổi chủ đề, quay lại đơn cũ | S08 26% sau xem xét | 150 |
| T09, T11, T12 chèn lệnh (PDF, tin nhắn, mô tả SP), lừa đảo | Qwen làm theo lệnh chèn ≥4 lần | 200 |
| T11 Trợ lý ca soạn nháp nhiều tool | F52 trả lời rỗng ở lần gọi cuối | 150 |
| T07, T10 khách bức xúc/dọa, ngoài phạm vi | giữ năng lực đã tốt | 100 |

**Ghi chú S12 (phân tích 16/11):** Qwen thua DeepSeek 42 điểm ở S12 (52% so với 94%), nhưng **gần như không do bị lừa** (ca giả danh shipper 3/3, giả danh kho 2/3). Lỗi chính là **quy trình tri thức**: trích dẫn thiếu/sai 11, thiếu nguồn chính sách 5, không tra tri thức hoặc không tra đơn trước khi trả lời 3; ngoài ra mở biểu mẫu trả hàng khi đơn đã quá hạn (livestream, 0/3), không chuyển nhân viên khi xin hóa đơn VAT (0/3). Khung T12 vì vậy nhấn: tra đơn + tra chính sách + trích dẫn đúng trong ngữ cảnh lừa đảo/COD/đồng kiểm/11.11/Tết; biết khi nào chỉ trả lời, khi nào chuyển nhân viên. Điểm yếu an toàn thật (làm theo lệnh chèn) nằm ở **S11** (Trợ lý ca đọc PDF/tin nhắn) và `s09_015`.

## 5. Ngân sách

| Hạng mục | Ước |
|---|---|
| DeepSeek: 2 lần/ca + đối chứng/dự phòng lời khách, ngoài giờ cao điểm | 2–5 USD (số dư 4,42 → nạp thêm ~5 USD) |
| Muse Glimmer viết lời khách trên A100 40 GB (đợt thử + 1.406 phiếu) | 2–4 đơn vị |
| Qwen ×4 trên A100 40 GB (+ đợt thử) | 12–20 đơn vị |
| Huấn luyện A100 40 GB | 15–25 đơn vị |
| Đo lại 250 × 3 trên L4 | ~3 đơn vị |
| **Tổng Colab** | **~30–50 / ~88 còn lại** |

## 6. Lịch (mốc: repo về private ~1/12; reset demo trước 15/12; nộp 19/12; bảo vệ 20–23/12)

| Ngày | Việc |
|---|---|
| 17–18/11 | Batch tài liệu W6.4 (§32 D18–D20, D12b); owner chấm lại audit |
| 17–21/11 | Code bước 1, 2, 5, 6 + test |
| 21–22/11 | Đợt thử 100 ca (đo 16/24/32 luồng; owner xem mẫu) |
| 23–26/11 | Sinh đủ 1.200 ca, xếp tier, dựng tập SFT |
| 26–29/11 | Huấn luyện |
| 29/11–1/12 | **Đo lại trước khi repo về private** (Colab clone repo công khai; sau 1/12 phải dùng token) |
| 2–19/12 | W6.5 (nếu kịp), W6.6 phát hành, viết khóa luận |

## 7. Còn chờ owner

1. ~~Ai viết code bước 1, 2, 5, 6~~ — đã chốt: Gemini Carbon điều phối Hydrogen (W6.7.0; phần A merge PR #120 ngày 2026-11-17).
2. ~~Người viết lời khách~~ — đã chốt 2026-11-17: **Muse Glimmer 30B** (§34 W6.7-D1). Đã loại: Gemini (Carbon đã viết 210 ca đo → trùng giọng giữa tập huấn luyện và tập đo; điều khoản cấm phát triển model cạnh tranh), GLM-5.3 qua Z.ai (Additional Terms 1.f.xii cấm dùng đầu ra để fine-tune model bên ngoài; Terms III.4.f), NVIDIA Nemotron 3 (không hỗ trợ tiếng Việt), DeepSeek làm người viết chính (vừa viết câu hỏi vừa làm thầy → "đá sân nhà").
