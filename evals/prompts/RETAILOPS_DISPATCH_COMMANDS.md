# RETAILOPS — CÁC LỆNH ĐIỀU PHỐI LÔ (DISPATCH COMMANDS)

Dùng kèm [`RetailOps_MASTER_PROMPT.txt`](RetailOps_MASTER_PROMPT.txt) và manifest [`RetailOps_BATCH_PLAN_250.json`](../manifests/RetailOps_BATCH_PLAN_250.json). Không cần gửi nguyên repository hoặc benchmark cũ cho mỗi lô: gửi hợp đồng, đúng `BATCH_SLOTS` và các fixture/chính sách liên quan là đủ. Không đưa `held_out` đã duyệt vào prompt tối ưu chatbot RetailOps.

---

## LỆNH 1 — LẬP HỒ SƠ ORACLE (`GIAI_DOAN=PLAN`)
*(Lưu ý: Đây KHÔNG phải dataset 9 trường, mà là hồ sơ đặc tả test conditions và assertions)*

```text
GIAI_DOAN=PLAN
BATCH_ID=B01
BATCH_SLOTS=<sao chép trường slots của B01 từ RetailOps_BATCH_PLAN_250.json>
FAMILY_REGISTRY=<family và split đã dùng ở các lô trước, lô đầu dùng []>
SOURCE_PACK=<fixture/chính sách bổ sung đã xác minh, không có thì để rỗng>
Hãy tạo đúng một hồ sơ cho mỗi slot. Giữ nguyên quota. Chỉ xuất JSON object theo hợp đồng PLAN.
```

---

## LỆNH 2 — KIỂM TOÁN NGHIỆP VỤ ĐỘC LẬP
*(Reviewer kiểm tra hồ sơ Oracle trước khi sinh lời khách)*

```text
Đọc MASTER_PROMPT, hồ sơ oracle ứng viên và source pack.
Không sinh thêm ca. Tìm lỗi theo: ownership; khả năng tool; thiếu fixture; yêu cầu mutation;
hứa handoff/đổi/hoàn tiền/voucher không có biên nhận; chính sách bị suy diễn; snapshot lỗi thời;
trùng scenario_family qua hai split; expected_tools không tối thiểu hoặc không thực thi được.
Xuất một JSON object:
{
  "approved_ids": [],
  "issues": [
    {
      "id": "...",
      "severity": "critical|major|minor",
      "field": "...",
      "evidence_path": "...",
      "problem": "...",
      "proposed_correction": "..."
    }
  ]
}
approved_ids chỉ là ý kiến của reviewer, không phải bằng chứng runtime.
Không sửa nhãn về hành vi đúng để hợp thức hóa bug hiện tại.
Người phụ trách dataset xác nhận bản hồ sơ cuối cùng trước bước tiếp theo.
```

---

## LỆNH 3 — SINH LỜI KHÁCH VÀ JSONL (`GIAI_DOAN=DATASET`)
*(DeepSeek chỉ viết `user_text` theo `intent_brief`, giữ nguyên 8 trường gold)*

```text
GIAI_DOAN=DATASET
OUTPUT_MODE=jsonl
APPROVED_ORACLE=<JSON hồ sơ lô đã duyệt, không phải bản ứng viên>
AVOID_TEXTS=<các câu đã sinh và các ví dụ calibration không được lặp>
Hãy xuất đúng số dòng bằng số entry, mỗi dòng 9 trường theo MASTER_PROMPT.
Không xuất hồ sơ fixture hoặc giải thích. Giữ nguyên 8 trường gold.
```

---

## LỆNH 4 — SỬA LÔ BỊ TỪ CHỐI (`GIAI_DOAN=REPAIR`)

```text
GIAI_DOAN=REPAIR
FAILED_ROWS=<dòng lỗi>
VALIDATOR_ERRORS=<lỗi thực tế>
APPROVED_ORACLE=<chỉ các entry tương ứng>
OUTPUT_MODE=jsonl
Chỉ xuất các ID yêu cầu sửa. Không đổi gold để làm validator im lặng.
Không bỏ dòng lỗi, không nuốt JSONDecodeError và không tự giảm số ca.
```

---

## LỆNH 5 — MỞ RỘNG SAU 250 CA (DÀNH CHO 2.000 – 5.000 MẪU SFT)

```text
Giữ nguyên tập lõi đã khóa. Tạo manifest bổ sung với prefix phiên bản riêng,
phân bố SOP công khai, cả hai split và đủ category nếu phát hành thành dataset độc lập.
Không tự đánh số tiếp mà bỏ qua kiểm tra family; không nhập các ca held_out lõi vào tập tuning.
Ưu tiên thêm fixture cạnh biên, lỗi hạ tầng và cặp phản thực tế thay vì paraphrase tăng số lượng.
```
