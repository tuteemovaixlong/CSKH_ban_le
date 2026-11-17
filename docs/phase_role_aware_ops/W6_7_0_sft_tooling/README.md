# W6.7.0 — Công cụ sinh dữ liệu chưng cất (SFT)

Handoff code cho kế hoạch [W6.7 đã chốt](../W6_7_sft_data/README.md) (§33 W6.4-D12b). Đọc theo thứ tự 01 → 08. **Owner: dán [07_PROMPT_CARBON.md](07_PROMPT_CARBON.md) cho Carbon.**

## Mục tiêu

Viết công cụ để owner sinh **1.200 ca huấn luyện chất lượng cao**, chạy Qwen3.5-9B và DeepSeek V4.1 Flash bằng **đúng runner của bộ đo**, chọn lượt tốt nhất, và dựng tập SFT. Hệ thống (`retailops/`, `agent_protocol.py`, `retailops_providers.py`, `data/knowledge/`) **không đổi**.

## Hai phần, hai PR

| Phần | Nội dung | Thiết kế | Dùng khi |
|---|---|---|---|
| **A** | Dữ liệu cửa hàng riêng `sft_v1`; runner nạp fixture `sft_v1` và tệp ca huấn luyện; bộ sinh khung ca; bước viết lời khách có kiểm bằng code (người viết chốt sau: Muse Glimmer 30B tự chạy, DeepSeek viết thay — §34 W6.7-D1, #123) | [03](03_THIET_KE_PHAN_A.md), [04](04_DANH_MUC_KHUNG_CA.md) | Trước khi chạy model |
| **B** | Chọn lượt và xếp tier (code + gói giám khảo); dựng tập SFT từ vết | [05](05_THIET_KE_PHAN_B.md) | Sau khi chạy model |

Phần B có thể làm ngay sau A (không cần dữ liệu thật để viết code; test dùng dữ liệu giả).

## Trạng thái (2026-11-17): xong, đã merge

| PR | Nội dung | Kiểm | Merge |
|---|---|---|---|
| #120 | Phần A | 3 vòng: [09](09_PHAN_HOI_PR120.md), [10](10_PHAN_HOI_PR120_V2.md), vòng 3 đạt | `20d623f` |
| #122 | Khung bù khe hở: `track_shipment`, `search_products` (T01 90, T02 100) | Claude viết | `4cfb209` |
| #123 | `sft_utterances`: Muse Glimmer tự chạy (không khóa, dòng system thêm, nhãn người viết) | Claude viết | `8fe6a63` |
| #121 | Phần B | 2 vòng: [11](11_PHAN_HOI_PR121.md) (P1–P4, N1; vòng 2 đạt, có chạy thử đầu cuối trên vết W6.4) | `68b6d08` |

Bước tiếp theo nằm ở notebook Colab: pilot lời khách trên A100, sinh quỹ đạo, chấm tier, huấn luyện. Xem kế hoạch [W6.7](../W6_7_sft_data/README.md).

## Phân vai

| Ai | Việc |
|---|---|
| **Gemini 4 Carbon** | Điều phối: giao việc cho bot Hydrogen, kiểm theo danh sách, dừng ở cổng ([07](07_PROMPT_CARBON.md)) |
| **Gemini 4 Hydrogen "H-code"** | Viết code + test, mở PR ([06](06_PROMPT_HYDROGEN.md)) |
| **Claude** | Kiểm mỗi PR một lượt; chuẩn bị notebook Colab (A100 cho Qwen, CPU cho DeepSeek) sau khi PR A merge |
| **Owner** | Merge; chạy các bước ở [08](08_SAU_KHI_MERGE.md); xem tay mẫu đợt thử 100 ca |

## Quy tắc

- **Không sửa:** `retailops/`, `agent_protocol.py`, `retailops_providers.py`, `data/knowledge/`, `evals/suites/*`, `data/demo_events/store_events.jsonl`, `scripts/eval_dataset_v2.py` (bộ kiểm ca đo), logic chấm của runner (`grade_turn`, `squash`, `attack_success`, `grade_final_state`).
- **Không làm hỏng đường đo**: mọi thay đổi ở `scripts/run_agent_scenarios.py` chỉ thêm nhánh mới cho fixture `sft_v1` và ca huấn luyện (`id` bắt đầu bằng `t`); ca đo và fixture `standard`, `late_voucher_issued` chạy y như cũ (có test chứng minh).
- **Không gọi API LLM thật trong lúc phát triển hay test.** Mã gọi DeepSeek chỉ chạy khi owner chạy; test dùng client giả. Không dán khóa. Khóa đọc từ biến môi trường `DEEPSEEK_API_KEY`.
- Không thêm thư viện. Không merge, không push `main`, không force-push/rebase/reset/stash, không đổi biến/secret repo, không deploy, không chạm EC2/SSM/Colab/production.
- 250 ca đo **không bao giờ** vào dữ liệu huấn luyện: ca huấn luyện dùng `sft_v1`, lời khách mới, có bộ lọc trùng.
- Câu hỏi hay mâu thuẫn: hỏi owner bằng câu hỏi trắc nghiệm ngắn.
