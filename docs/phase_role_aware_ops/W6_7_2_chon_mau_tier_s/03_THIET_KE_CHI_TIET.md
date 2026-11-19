# 03 — Thiết kế chi tiết

Hằng số dùng chung (đặt trong `scripts/sft_select.py`, có chú thích quyết định owner 19/11):
- `HARD_SUITES = {'T05','T06','T08','T11','T12'}`; `EASY_TIGHT = {'T09','T10'}`.
- `SECOND_CAP = 0.5` (khung thường), `SECOND_CAP_TIGHT = 0.25` (T09, T10); `DEEPSEEK_SHARE_CAP = 0.35`.
- `QWEN_SECOND_MAX_SIM = 0.85`; độ giống = `difflib.SequenceMatcher(None, n(a), n(b)).ratio()` với
  `n(s) = re.sub(r'\s+', ' ', re.sub(r'[*#`>|_-]', '', s.lower()))[:3000]`, `a`/`b` = các lượt `turns_text` nối bằng `\n`.
  Chỉ dùng giữa hai lượt **cùng model**; hai model khác nhau thì câu chữ luôn khác (đo: trung vị 0,05–0,14).
- `CJK = r'[぀-ヿ㐀-䶿一-鿿가-힯]'`.
- Danh sách loại trừ truyền bằng `--exclude-templates` (không ghim trong code): 6 khung W6.7.1 + `t07_doa_dang_bai`.

## A. `export --round 2` — Qwen trước, ba lớp ứng viên
CLI: `sft_select export --scores S --out DIR --round 2 --after ADJ [ADJ …] --max-tool-chars 8000 --exclude-templates …`.
`--after` nhận nhiều tệp; ứng viên đã có trong bất kỳ tệp nào coi là đã chấm; Tier lấy theo tệp **sau cùng** chứa nó.
Chỉ lấy `A_code` (bỏ hẳn `B_code`). Mỗi ca tối đa một ứng viên mỗi lớp:

| Lớp (`cls`, chỉ ghi trong `map.json`) | Ca được xét | Ứng viên |
|---|---|---|
| `q_next` | ca **chưa có Tier A** | A_code Qwen chưa chấm, rank tốt nhất. Không có → ca không xuất (sang W6.7.3) |
| `ds_pair` | Tier A tốt nhất của ca là **Qwen** | A_code DeepSeek chưa chấm, rank tốt nhất (nguồn Tier S + mẫu thứ hai bộ khó) |
| `q_second` | bộ ∈ `HARD_SUITES`, Tier A là Qwen, **không** có A_code DeepSeek chưa chấm | A_code Qwen chưa chấm, rank tốt nhất trong các lượt có độ giống với mẫu Tier A < 0,85 |

Gói (`packets/`) giữ nguyên định dạng và rubric vòng 1 (`kind: sft_tier`, `REQUIREMENT_TEXT`, ẩn model/ca/lượt/lớp),
câu cắt kết quả tool lấy theo `--max-tool-chars`. `map.json` thêm `cls` cho từng ứng viên, `max_tool_chars`, danh sách
`after`. Dữ liệu thật (Claude đối chiếu sau merge): `q_next` 193, `ds_pair` ≤ 290.

## B. Trọng tài (đưa bản thử `scratch/w67_trong_tai/*` vào repo)
- `export --arbiter --base ADJ --scores S --out DIR --max-tool-chars 8000`: chọn ứng viên `tier == 'B'`,
  `code_tier == 'A_code'`, không mục nào `any_khong_dat`; gửi mọi mục chưa `both_dat`. Dựng lại từng mục bằng chính
  hàm của `export`, **giữ `item_id` của vòng gốc**; chặn an toàn: dựng lại ở số ký tự của vòng gốc phải trùng
  `text` trong `map.json` gốc, lệch thì dừng. Ghi `packets/`, `map.json` (`pair_r1` = cặp phiếu gốc).
- `import --arbiter --judge-dir DIR --base ADJ --out OUT [--strict-kckc]`: phiếu một người ở `verdicts/batch-NN.jsonl`;
  `dat` (trích dẫn hợp lệ) → mục coi như dat/dat; `khong_dat` (hợp lệ) → mục `any_khong_dat`; còn lại giữ nguyên.
  `--strict-kckc`: mục kc/kc mà trọng tài `dat` vẫn giữ B. Xếp lại Tier như `import_judge_round`, ghi thêm
  `arbiter_raw`, `arbiter`, `arbiter_reason`, khối `arbiter` (luật, đếm, trích dẫn bị hạ).
- Kiểm: chạy lại trên bộ giả phải cho đúng kết quả của bản thử (bản thử cho 478 → 548 ca Tier A trên dữ liệu thật).
- Lưu ý: bản thử viết trước W6.7.1 nên gán thẳng hằng `MAX_TOOL_RESULT_CHARS`; W6.7.1 đã bỏ hằng đó, dùng tham số
  `max_tool_chars` của `_extract_turn_steps`/`export_judge_round` (`DEFAULT_MAX_TOOL_CHARS = 3000`) — code mới dùng tham số.

## C. Tier S — chấm cặp
**Xuất** `sft_select export-tier-s --scores S --adjudicated ADJ --out DIR --max-tool-chars 8000`: với mỗi ca có ≥ 2 ứng
viên Tier A, ghép **mẫu chính** (Qwen tốt nhất nếu có) với **từng** ứng viên Tier A còn lại. Một mục = một lượt hội
thoại: `{"item_id","kind":"sft_tier_s_cap","context","mau_1":{"steps","answer"},"mau_2":{"steps","answer"},
"requirement"}`; thứ tự `mau_1`/`mau_2` xáo theo seed, `map.json` ghi mẫu nào là mẫu nào. Lô 20 mục.

**Rubric Tier S** (hằng `TIER_S_RUBRIC`, in bằng `--print-rubric-s`). Mỗi mẫu là `S` khi đã là Tier A và đạt **đủ 7 tiêu
chí**, mỗi tiêu chí kèm một trích dẫn nguyên văn từ chính mẫu đó:
1. **Đầy đủ** — trả lời mọi ý khách hỏi trong lượt.
2. **Đúng trọng tâm** — suy luận nêu đúng dữ kiện quyết định từ kết quả tool (trạng thái, hạn, điều kiện) và đi thẳng
   tới kết luận, không vòng vo, không tự mâu thuẫn.
3. **Giàu thông tin hữu ích** — chủ động nêu thêm điều khách sẽ cần (hạn còn lại, trạng thái hoàn tiền, phí, bước tiếp
   theo, lựa chọn thay thế hợp lệ). Mọi câu thêm phải có căn cứ trong kết quả tool/KB và liên quan đến việc của khách;
   câu xã giao, lặp lại, chung chung không được tính, nhiều câu như vậy thì trượt tiêu chí này. Không chấm theo độ dài.
4. **Dùng tool tiết kiệm** — không gọi trùng, không gọi thừa so với điều cần kiểm.
5. **Dẫn đúng nguồn** — chính sách nêu ra khớp đúng tài liệu KB được trích.
6. **Đúng quy trình** — bước xử lý (mở biểu mẫu, chuyển nhân viên, hướng dẫn) đúng chính sách, không hứa vượt chính sách.
7. **Rõ ràng với khách Việt** — bố cục dễ đọc, tiếng Việt tự nhiên, không lẫn chữ nước ngoài (Hán/Nhật/Hàn…).
Thêm cho cặp: `tot_hon` ∈ {`mau_1`,`mau_2`,`ngang`}; `khac_biet` ∈ {`cach_xu_ly` (khác hướng giải quyết/thứ tự
kiểm tra), `thong_tin` (khác thông tin hữu ích đưa cho khách), `chi_cau_chu`}. Dặn giám khảo: không đoán model, không
thiên vị câu dài, thứ tự hai mẫu là ngẫu nhiên.

**Phiếu** (một dòng/mục): `{"item_id","mau_1":{"S":bool,"bang_chung":{"1":"…",…,"7":"…"},"truot":[số tiêu chí]},
"mau_2":{…},"tot_hon":"…","khac_biet":"…","reason":"…"}`.

**Nhập** `sft_select import-tier-s --judge-dir DIR --adjudicated ADJ --out OUT`: `S = true` chỉ được giữ khi đủ 7 trích
dẫn, mỗi trích dẫn ≥ 8 ký tự và có trong văn bản của **đúng mẫu đó** (chuẩn hóa như `eval_regrade.v2`); thiếu/sai → S
= false (ghi `downgraded_s`). Ứng viên là **Tier S khi mọi lượt đều S**. Cặp **khác nhau** khi chuỗi tên tool (mọi lượt,
theo thứ tự) khác nhau, **hoặc** có lượt `khac_biet` ∈ {`cach_xu_ly`,`thong_tin`}. Ghi `tier_s`, `s_pairs` vào tệp ra.

## D. `select` mới
Vào: `--scores`, `--adjudicated` (sau vòng 2 + trọng tài + Tier S), các hằng ở đầu tệp. Với mỗi ca:
- **Mẫu chính**: Qwen tốt nhất (S trước A, rồi rank); không có Qwen Tier A → DeepSeek tốt nhất (S trước A).
- **Mẫu thứ hai** (tối đa một, xét theo thứ tự, lấy cái đầu tiên đạt):
  1. DeepSeek **S**, khác mẫu chính (mục C) — mọi bộ.
  2. Qwen **S** khác lượt mẫu chính, độ giống < 0,85 — mọi bộ.
  3. Bộ khó: DeepSeek Tier A (không cần S).
  4. Bộ khó: Qwen Tier A khác lượt, độ giống < 0,85.
  5. Mẫu chính là DeepSeek: chỉ nhận DeepSeek **S** khác mẫu chính.
- **Trần khung**: số ca có mẫu thứ hai ≤ `floor(SECOND_CAP × số ca có mẫu chính)` của khung (`SECOND_CAP_TIGHT` cho T09,
  T10). Vượt trần thì bỏ mẫu thứ hai ưu tiên thấp trước (1 > 2 > 3 > 4 > 5), cùng hạng bỏ theo băm `case_id` + seed.
- **Trần DeepSeek**: tổng mẫu DeepSeek (chính + thứ hai) ≤ `DEEPSEEK_SHARE_CAP × tổng mẫu`. Vượt thì chỉ bỏ **mẫu thứ
  hai** DeepSeek: bộ không khó trước, Tier A trước S, rồi theo băm. Không bao giờ bỏ mẫu chính.
- Ra `selection.json`: mỗi mẫu `case_id, model, run, role (primary|second), tier (A|S), rule (1–5)`; báo cáo trần đã áp,
  đếm theo bộ × nguồn × tier × vai, tỉ trọng DeepSeek. `--max-per-case 1` → chỉ mẫu chính, phải trùng `select` cũ
  trên cùng đầu vào khi không có S.

## E. `sft_build`
- Nhận nhiều mẫu/ca (id mẫu thêm hậu tố `#2`); hai mẫu cùng ca luôn cùng tập train/val (đã tách theo khung).
- Nhãn trong `meta` mỗi mẫu: `source` (`qwen`|`deepseek`), `tier` (`A`|`S`), `role`, `owner_edit` (`cjk`|null).
- `--owner-edits PATH` (`owner_edits_cjk.jsonl`: `case_id, model, run, old, new`): áp thay `old → new` trên mọi
  `content`/`reasoning_content` của trợ lý (tin cuối và tin trợ lý trước đó trong `request.messages`) của các mẫu thuộc
  lượt chạy đó; mỗi dòng phải áp được ít nhất một lần, không thì dừng có lỗi. Vết gốc không bị sửa.
- **Chặn chữ Hán**: sau lớp phủ, văn bản trợ lý còn khớp `CJK` → loại mẫu, lý do `cjk_text`; báo cáo liệt kê để xuất đợt
  CSV tiếp theo.
- Báo cáo thêm: đếm theo bộ × nguồn × tier × vai, số mẫu `owner_edit`, số mẫu loại vì `cjk_text`.

## F. `scripts/sft_cjk.py` (đưa bản thử `scratch/w67_cjk/*` vào repo)
- `export --scores S --selection SEL --out CSV`: với mỗi mẫu trong `selection.json`, lấy chữ từ vết gốc (tin `stop` cuối
  mỗi lượt: `content`, `reasoning_content`; và tin trợ lý trong `request.messages`), mỗi đoạn `CJK` một dòng:
  `stt, ma_mau (case|model|run), luot, truong (tra_loi|suy_luan|tin_truoc|tin_truoc_suy_luan), chu_han, doan_chua (±50
  ký tự, đoạn trong ⟦ ⟧, xuống dòng → " ⏎ "), sua_thanh (trống)`; bỏ dòng trùng (tin lượt trước lặp trong request lượt
  sau); UTF-8 có BOM; không ghi đè tệp đã có.
- `import --csv CSV --scores S --out owner_edits_cjk.jsonl [--check-only]`: kiểm mọi dòng đã điền; bản sửa không còn
  `CJK`, ≤ 40 ký tự, không thêm chữ số mới; `(xóa)` = bỏ đoạn (gộp khoảng trắng hai bên); **thêm dấu cách** vì chữ Hán
  thường dính liền chữ Việt: trước chữ thay nếu ký tự bên trái là chữ/số hoặc một trong `, ; : . ! ? )`, sau chữ thay nếu
  ký tự bên phải là chữ/số hoặc `(` (bản thử thiếu luật này đã cho ra "áo bịnhăn", "hơn,bạn"); đoạn cũ kèm 20 ký tự ngữ cảnh
  mỗi bên phải có trong vết gốc của mẫu; ghi đè các dòng cũ cùng `source_csv`, giữ dòng của tệp khác.
- **Code không điền `sua_thanh`**, không gợi ý chữ thay.
