# Chạy RetailOps trực tiếp trên Colab

Mở `colab_inference.ipynb` trong Google Colab, chọn runtime GPU và chạy từng ô.
Notebook chứa source Python, dữ liệu smoke và tests; không cần upload ZIP,
clone repository private hoặc nhập token GitHub.

1. Ô source: kiểm tra SHA-256, ghi source vào `/content/retailops_colab_direct`,
   chạy 41 offline tests. Kết quả: `SOURCE_READY`.
2. Ô runtime: kiểm tra GPU, cài `curl`, `zstd`, Ollama khi chưa có, dùng lại
   server đang trả lời hoặc khởi động server. Kết quả: `MODEL_READY`.
3. Ô thử một câu: JSON đề xuất hủy O-101 và `ollama ps`.
4. Ô evaluation: 24 mẫu tổng hợp, tắt cache kết quả, ghi báo cáo và SQLite.
5. Ô ngrok là tùy chọn, tắt mặc định; các token lấy từ Colab Secrets.
6. Tải ZIP kết quả trước khi đóng runtime. Ô cuối dừng server do notebook tạo.

Source hash được lưu để so sánh với phiên bản triển khai EC2. Notebook giữ
nguyên schema, prompt, validator và evaluator của baseline; không có đường
inference khác bị gọi là cùng một baseline. Output JSON không thực hiện hủy đơn.

Không sử dụng Run all: ô cuối dừng server. Chỉ dùng dữ liệu giả lập vì source
vẫn lưu nguyên văn request/output. Không có anti-idle, tự reconnect hoặc tự
chuyển sang model trả phí. GPU và thời gian runtime do Colab cấp phát.

## Cập nhật source được nhúng

Sau khi thay đổi source baseline, proxy, backup hoặc tests/data, chạy từ repo:

```bash
python scripts/build_colab_notebook.py
```

Commit notebook đã tạo cùng với thay đổi source. `notebooks/colab_runtime.py`
chứa ô setup runtime để chỉnh sửa dễ hơn.

## Phạm vi xác minh

41 offline tests và cú pháp các ô Python đã được kiểm tra. Phần nguồn tự chứa
được chạy trong thư mục tạm để xác minh không cần ZIP. Các trường hợp thiếu GPU
và chạy lại với server đã sẵn sàng được kiểm tra bằng mock.

Chưa có traceback từ phiên lỗi ban đầu, nên chưa kết luận nguyên nhân cụ thể.
Chưa chạy GPU Colab hay inference Qwen thật trong môi trường của trợ lý.

Nguồn: [Ollama Linux](https://docs.ollama.com/linux),
[Ollama installer](https://github.com/ollama/ollama/blob/main/scripts/install.sh),
[Colab FAQ](https://research.google.com/colaboratory/faq.html).
