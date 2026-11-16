# 06 — Sau khi merge

Executor **không** làm phần này. Claude và owner làm theo thứ tự.

## 1. Kiểm chứng và merge

1. Claude kiểm PR một lượt theo [02](02_PHAM_VI_VA_TIEU_CHI.md): đọc diff, chạy lại test mới và các lệnh ở [04](04_TEST_VA_KIEM_TRA.md) mục 3, so các số đo.
2. CI xanh đủ 6 job (kể cả lượt test trong image của job `offline`).
3. Owner merge. Claude merge thì phải có `--match-head-commit` với SHA đầy đủ.

## 2. Deploy và đặt cửa sổ 32k trên production

1. Owner bật EC2 và chạy kiểm giai đoạn 1 như các lần trước. Claude bật cờ deploy, chạy workflow, tắt cờ ngay khi job deploy bắt đầu chạy.
2. Sau khi rollout xong, owner thêm vào `api.env` trên EC2 (qua SSM, dùng `nano`, không dán giá trị khóa vào chat):

```text
RETAILOPS_MODEL_CONTEXT_TOKENS=32768
```

3. Tạo lại container `web` để nạp biến mới (`cweb` lấy từ khối khởi tạo phiên):

```bash
"${cweb[@]}" up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 90 web
```

4. Kiểm: `grep -c '^RETAILOPS_MODEL_CONTEXT_TOKENS=32768$' api.env` ra `1`; `healthz=200`.

DeepSeek nhận ngữ cảnh lớn hơn nhiều, nên 32k an toàn. Khi chuyển sang Qwen trên Colab ở chế độ demo (§32 W6.4-D5a), vLLM phải chạy `--max-model-len 32768`, khớp với biến này.

## 3. Smoke

| # | Tin nhắn | Kỳ vọng |
|---|---|---|
| 1 | liệt kê các đơn của tôi | đủ **3/3** đơn, mỗi đơn có trạng thái, ngày, số tiền và món; không còn câu kiểu "đơn thứ 3 chưa hiển thị" |
| 2 | đơn `<mã>` gồm những gì, giá bao nhiêu | đúng như lần smoke W6.4.0 (lấy từ `get_order`) |
| 3 | còn đơn nào nữa không | không bịa thêm đơn; nếu `has_more` là false thì nói đã đủ |

## 4. Lượt đo W6.4 ở 32k (§32 W6.4-D9a)

- Cell Colab (`scratch/colab_w64_cells.py`): đổi `REPO_SHA` sang commit merge của W6.4.1. Trong `STAGES`, đặt ngữ cảnh 32768 cho `examples`, `pilot`, `A`, `B`, `C` và hai bước hồi quy; `D` giữ 8192.
- vLLM `--max-model-len 32768`. Qwen3.5-9B dùng kiến trúc lai nên KV cache rất nhỏ: lượt thử trên L4 chỉ dùng 5–6%.
- Ghi vào biên bản W6.4 là cấu hình A dùng 32k, khác D9 ban đầu, theo D9a.
