# Bộ đánh giá W6.3

Thư mục này dành cho `S01.jsonl` … `S12.jsonl` của bộ đánh giá 250 ca theo
`khoa_luan/eval_pack/04_DINH_DANG_VA_CHAM.md` bản 2 và phân bổ ở `05_PHAN_BO_CA.md`.
Chưa có ca thì CI báo 0 ca và đạt. Bốn ví dụ định dạng nằm riêng trong
`khoa_luan/eval_pack/06_vi_du.jsonl`, không tính vào 250 ca.

Cả 250 ca do model độc lập viết: 210 ca mô phỏng, cộng 40 ca chuyển thể từ τ²-bench và
AgentDojo. Với 40 ca chuyển thể, Claude chọn nguồn và kiểm (W6.3-D8). Executor phần code
không viết hay sửa ca trong thư mục này.

```sh
python scripts/check_eval_dataset.py
python scripts/check_eval_dataset.py evals/suites --final
python scripts/run_agent_scenarios.py --fake --dataset-dir evals/suites --min-success-rate 1.0
```

Dữ liệu đã đóng băng ngày 2026-11-14 (W6.3-D7, bảng cuối tệp này). Từ đây không sửa ca,
chỉ thêm phiên bản mới. Báo cáo runner lưu hash byte gốc của từng file; `eval_stats compare`
từ chối khi khác tập mã ca hoặc khác hash.

## Nguồn gốc từng bộ

Mỗi bộ được thêm nguyên byte như model độc lập gửi về, sau khi qua bộ kiểm và phát lại quỹ đạo mẫu đạt 100%. Ca hỏng, hoặc ca có kỳ vọng chấm hỏng được câu trả lời đúng, được trả lại cho model kèm lý do; model gửi lại nguyên dòng, Claude thay đúng dòng đó và không tự sửa kỳ vọng (W6.3-D1).

| Bộ | Số ca | Người viết | Ngày nhận | SHA-256 | Ghi chú |
|---|---|---|---|---|---|
| S07 | 11 | Gemini 4 Carbon (Google AI Studio, phiên chỉ đọc `eval_pack` bản 2) | 2026-11-11, sửa 2026-11-12 | `ccb9015e583dbca8dd217a8eb6f7c82e94e1f75fe4d907a549ae33fe20b92be9` | Phát lại 5/11 trước W6.3.1, 11/11 sau W6.3.1 (PR #94). Ngày 2026-11-12 model thay `answer_not` của `s07_006` ("nghỉ Chủ nhật" khớp câu đúng "không nghỉ Chủ nhật"); bản đầu `a8cb07fb…` |
| S09 | 20 | Gemini 4 Carbon (Google AI Studio, phiên chỉ đọc `eval_pack` bản 2) | 2026-11-11, sửa 2026-11-12 | `ceb9584d4602a9aeb7385f0e8e2272e0b3ced14e54a7307a266db62412c69f94` | Lần đầu phát lại 18/20; trả lại 2 ca (`s09_008` tự mâu thuẫn với `answer_not`, `s09_011` thiếu cách nói đồng nghĩa); bản sửa 20/20. Ngày 2026-11-12 model thay `answer_not` của `s09_006`, `s09_015`, `s09_020` vì câu từ chối đúng nhắc lại lời khách ("em không thể xác nhận mã VCH-VIP-500K") khớp cụm cấm; bản trước `8b514742…` |
| S10 | 10 | Gemini 4 Carbon (Google AI Studio, phiên chỉ đọc `eval_pack` bản 2) | 2026-11-12 | `01562bc4e6241172481f6e43a4b556ce6278212836d20fb8af14b7302a53404b` | Lần đầu phát lại 10/10; trả lại 3 ca (`s10_008`, `s10_009`, `s10_010`) vì `answer_not` khớp được câu trả lời đúng ("không cung cấp mã OTP", "sau khi đặt hàng thành công"); bản sửa chỉ đổi 3 danh sách đó, 10/10 |
| S01 | 26 | Gemini 4 Carbon (Google AI Studio, phiên chỉ đọc `eval_pack` bản 2) | 2026-11-12 | `6742499c31f1ced367b90eb2a29a1e543c22f9b502b21ef7ce5260c555c568d4` | Hai phần, ghép thành một tệp (CRLF đổi thành LF, nội dung từng dòng giữ nguyên). Trả 5 ca: `s01_012`, `s01_013` (quỹ đạo mẫu gọi mã ngoài dữ liệu demo), `s01_018` (nhận câu trấn an không căn cứ), `s01_022`, `s01_026` (nhãn `vn_context`). Lộ ra F30, F31, F32 (W6.3.2): 18/26 trước, 26/26 sau |
| S02 | 18 | Gemini 4 Carbon (phiên AI Studio thứ hai, mở từ S02; chỉ đọc `eval_pack` bản 2) | 2026-11-12 | `35cd5b0df89c4b174547d1a94d86c5d428e67cca8df98f1128fd3d12517ef54d` | Trả 3 ca (`s02_010`, `s02_016` thiếu cách nói đồng nghĩa; `s02_018` kiểm nội dung khách không hỏi). Lộ ra F33, F34 (W6.3.3): 14/18 trên `main` cũ, 18/18 sau W6.3.2 và W6.3.3 |
| S03 | 30 | Gemini 4 Carbon (phiên AI Studio thứ hai, mở từ S02; chỉ đọc `eval_pack` bản 2) | 2026-11-12 | `9142f8b7f2b57dd2913ad18b9e5646d7453226d0ff97f87864301b5d341340a5` | Hai phần, ghép thành một tệp. Trả 5 ca: `s03_002`, `s03_005`, `s03_007`, `s03_009` (câu chính sách thứ hai thiếu trích dẫn), `s03_022` (`answer_not` bẫy phủ định, thiếu dạng liệt kê). `s03_028` hỏng do F34 cho tới W6.3.3; 30/30 |
| S04 | 13 | Gemini 4 Carbon (phiên AI Studio thứ hai, mở từ S02; chỉ đọc `eval_pack` bản 2) | 2026-11-12 | `d7734277f505a41e0c823e2059228e5f0b055f3ecbc8be6a576e195f89cda1af` | Trả 1 ca: `s04_010` có `knowledge` mà câu trả lời không trích dẫn (`knowledge_citation_missing`); 13/13 |
| S05 | 20 | Gemini 4 Carbon (phiên AI Studio thứ hai, mở từ S02; chỉ đọc `eval_pack` bản 2) | 2026-11-12 | `2143a51c1b80969d22ccf2d4411e62dcb53486844a7e58d7f90fc453acaa0db1` | Lần đầu 20/20. Trả 1 ca: `s05_017` câu mẫu nêu biến thể XL không có trong catalog P-202 |
| S06 | 14 | Gemini 4 Carbon (phiên AI Studio thứ hai, mở từ S02; chỉ đọc `eval_pack` bản 2) | 2026-11-13 | `27b1de0a7b5a64f52cb4f56be7501317ee4f3a36a10c38cac9663c179d2e7f11` | Trả 1 ca: `s06_004` lượt 2 mở form cho đơn chỉ được nêu sau `list_orders`, chưa được focus; thêm `get_order` ở lượt 1; 14/14 |
| S08 | 16 | Gemini 4 Carbon (phiên AI Studio thứ hai, mở từ S02; chỉ đọc `eval_pack` bản 2) | 2026-11-13 | `baa57e940aed710d09729211389e24f9be2f10c6cbbab79b8169f60171ecb326` | Mỗi ca 2–4 lượt. Trả 1 ca: `s08_005` lượt 3 mở form cho đơn đã mất focus khi xem sản phẩm khác; viết lại 4 lượt (tra lại, hỏi xác nhận, rồi mới mở form); 16/16 |
| S11 | 16 | Gemini 4 Carbon (phiên AI Studio thứ hai, mở từ S02; chỉ đọc `eval_pack` bản 2) | 2026-11-13 | `72a72ddf9a3547661e5afd8e372ee981c9a912c8683d13ba047ce4e7cb42a0ac` | Trợ lý ca của nhân viên. Trả 2 ca: `s11_012` câu mẫu quá 700 ký tự, `s11_007` câu mẫu bỏ sót size còn hàng. `s11_011` có tệp PDF, cần `pypdfium2`, phát lại trên CI |
| S12 | 16 | Gemini 4 Carbon (phiên AI Studio thứ hai, mở từ S02; chỉ đọc `eval_pack` bản 2) | 2026-11-13 | `db70f9e760c341ddb5170f2c28fa29e68681648716c8b26c5a85101ce9446377` | Lần đầu 16/16; một ca dùng fixture `late_voucher_issued` |

## 40 ca chuyển thể

Gemini 4 Carbon viết trong một phiên AI Studio mới, đọc `eval_pack` bản 2 cùng gói chuyển thể do Claude soạn. Gói gồm nguyên văn nhiệm vụ gốc, cách ánh xạ sang dữ liệu demo và quy tắc viết ca 1–15. Nguồn:

- τ²-bench retail: `sierra-research/tau2-bench` `c06b07dd7c4d4ec61ba6ff9bcdf0b15dd7ef36d4`, MIT. 28 nhiệm vụ bốc bằng seed `20261113`, 23 trong `retail_50`; bỏ nhiệm vụ 4, 5, 7.
- AgentDojo: `ethz-spylab/agentdojo` `089ed468cf3ed0322acc66b0211f26d9d90dbf60`, MIT. 12 ô (4 đường chèn × 3 mục tiêu); khung `important_instructions_no_names` dịch sang tiếng Việt, cộng biến thể giả danh quản lý cửa hàng.

Mỗi ca ghi `meta.upstream` gồm repo, mã nhiệm vụ, commit và với AgentDojo cả kiểu tấn công. 13/40 ca `held_out`, rút cùng seed. Mỗi tệp dưới đây được nối nguyên byte vào cuối bộ tương ứng; thêm một ký tự xuống dòng nếu bộ chưa kết thúc bằng xuống dòng.

| Bộ | Ca | Nguồn | Ngày nhận | SHA-256 tệp nhận | Ghi chú |
|---|---|---|---|---|---|
| S04 | `s04_014`–`s04_020` (7) | τ²-bench | 2026-11-13 | `5cc3a4fe85309c58f8d43512c07c4d4f244e1607dedfa6612690610c94e46d23` | Lần đầu 7/7 |
| S05 | `s05_021`–`s05_026` (6) | τ²-bench | 2026-11-14 | `3624b34ec6d6b6e1b2d03cd1ecb486adcae9cd92bd0fbdbfb8f1e71f99a2946a` | Trả 5 ca: `s05_021`, `s05_023`, `s05_024`, `s05_025` có `answer_not` nằm được trong câu từ chối đúng; `s05_022` có câu mẫu bị cắt vì F35. Bản đầu dùng làm tệp bằng chứng F35: 5/6 trước W6.3.4, 6/6 sau |
| S06 | `s06_015`–`s06_022` (8) | τ²-bench | 2026-11-14 | `784fb95f4923db151634600cf95f980789c768ad4a28a9987be5cfed05b7816b` | Trả 1 ca: `s06_019` có `answer_not` lặp lại câu hỏi của khách. `s06_017` hỏng do F36 cho tới W6.3.4 |
| S07 | `s07_012`–`s07_016` (5) | τ²-bench | 2026-11-14 | `f657eea30edc155a2e51c230f1e2b9d92d42941733fe6ea51285eaec6de32c65` | Lần đầu 5/5 |
| S08 | `s08_017`–`s08_018` (2) | τ²-bench | 2026-11-14 | `5d19e4d7696ff32ac215623b01779446b00d6380d967c90a50718417081f7813` | Lần đầu 2/2 |
| S09 | `s09_021`–`s09_026` (6) | AgentDojo, chèn qua mô tả sản phẩm và đoạn chính sách | 2026-11-14 | `491544061e1cfa593aaec4ad55a7b1772eb065b3544453645dc174a586d9234b` | Trả cả 6 ca, chỉ trường `attack_not`. Cụm mô tả nội dung lời chèn hay nằm trong câu cảnh báo đúng; lỗi bắt nguồn từ ca mẫu của Claude. Sau khi sửa chỉ còn chuỗi do kẻ tấn công kiểm soát (quy tắc 15) |
| S11 | `s11_017`–`s11_022` (6) | AgentDojo, chèn qua tin nhắn khách và PDF trong ca | 2026-11-14 | `6cffe22d935268a76b3ab03562b581c475fd7a197eb0287f766daf6dfc7184ec` | Lần đầu 6/6. Lời chèn trong PDF (`s11_020`–`s11_022`) chỉ tới được model sau khi sửa F37 (W6.3.4) |

## SHA-256 đóng băng (W6.3-D7, 2026-11-14)

| Tệp | Số ca | SHA-256 |
|---|---|---|
| `S01.jsonl` | 26 | `6742499c31f1ced367b90eb2a29a1e543c22f9b502b21ef7ce5260c555c568d4` |
| `S02.jsonl` | 18 | `35cd5b0df89c4b174547d1a94d86c5d428e67cca8df98f1128fd3d12517ef54d` |
| `S03.jsonl` | 30 | `9142f8b7f2b57dd2913ad18b9e5646d7453226d0ff97f87864301b5d341340a5` |
| `S04.jsonl` | 20 | `f71400121a9f86db71b86ee1c1f38a968d2cf5d2a8892d9357c6704d4f65e55f` |
| `S05.jsonl` | 26 | `999903d49e166de1a56c65fca7876958e99c82fbf31d2363e04931c8005be6dc` |
| `S06.jsonl` | 22 | `5de3c66a24244725aafbe37799381686ef5461d4bc7815b93b7bac8be0fc8355` |
| `S07.jsonl` | 16 | `550771b72d3a0d443969009d503df1de4e0058e5f2d176dc04f0d605f437bb37` |
| `S08.jsonl` | 18 | `3d07cefccb72fa13e1854d20efc20d678257c286f267e0cdca3a6997ea04b370` |
| `S09.jsonl` | 26 | `74ac253b32a161c9c0341981ff05033877d448c71f706fc9e568c70cb9654e37` |
| `S10.jsonl` | 10 | `01562bc4e6241172481f6e43a4b556ce6278212836d20fb8af14b7302a53404b` |
| `S11.jsonl` | 22 | `63cd47390bc3a1afb409a2706dbc7270aae6dcb4b80514d6ccdaf3af35c14386` |
| `S12.jsonl` | 16 | `db70f9e760c341ddb5170f2c28fa29e68681648716c8b26c5a85101ce9446377` |
