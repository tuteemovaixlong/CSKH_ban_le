# 08 — Sau khi merge

## Sau khi PR phần A merge

1. **Claude** chuẩn bị notebook: Qwen trên A100 40 GB (dựa trên notebook đo W6.4: fp8 + MTP, `--max-num-seqs` 32, 24–32 runner, `--repeat 4`, `--dataset <tệp ca>`, `--trace-out`; bước đo 16/24/32 luồng ở đợt thử) và DeepSeek trên runtime CPU (dựa trên notebook tham chiếu: `--repeat 2`, ngoài giờ cao điểm).
2. **Owner** (máy mình, repo ở `main`), ngoài giờ cao điểm DeepSeek:
   ```text
   python scripts/sft_cases.py generate --out "E:\hệ thống\sft_v1" --pilot 100
   python scripts/sft_cases.py check --out "E:\hệ thống\sft_v1"
   python scripts/sft_utterances.py fill --dir "E:\hệ thống\sft_v1" --endpoint https://api.deepseek.com/chat/completions --model deepseek-flash --concurrency 8
   ```
   Xem nhanh `utterances_report.md` và vài ca ngẫu nhiên; báo Claude.
3. **Đợt thử 100 ca:** chạy hai notebook trên tệp ca đã điền; tải kết quả về.

## Sau khi PR phần B merge

4. Chọn lượt và xếp tier:
   ```text
   python scripts/sft_select.py score --cases <ca đã điền> --run qwen=<thư mục Qwen> --run deepseek=<thư mục DeepSeek> --out scores.json
   python scripts/sft_select.py export --scores scores.json --out "E:\hệ thống\sft_judge_r1" --round 1
   ```
   Giao các phiên Hydrogen chấm (nhóm A, B) theo hướng dẫn chấm tier; rồi `import`, `select` (vòng 2 nếu cần).
5. Dựng tập SFT: `python scripts/sft_build.py --selection selection.json --cases <ca đã điền> --out-dir "E:\hệ thống\sft_v1_dataset"`; gửi Claude `stats.json` và `build_report.md`. Claude đo độ dài bằng tokenizer thật, chọn GPU huấn luyện, chuẩn bị notebook LoRA.
6. Đợt thử đạt (owner xem mẫu, tỉ lệ ca có mẫu hợp lý) → sinh đủ 1.200 ca và lặp bước 2–5.
