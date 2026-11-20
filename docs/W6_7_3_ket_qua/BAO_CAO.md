# Báo cáo thực thi W6.7.3

[Báo cáo bổ sung G: loại vết cũ và chặn giá trị giả](BO_SUNG_G.md). Kết quả dưới đây thuộc lượt A–F.

Nhánh: `phase-r1-w6-7-3-khung-do`. Rẽ từ `origin/main` tại
`0780af0207c858c993e6d745923feb000bdf1e4d`, sau `git fetch origin`.
SHA đầu nhánh sau commit/push được ghi trong tin bàn giao đi kèm báo cáo này.
Commit mã đã kiểm: `91f5faa4b6deeb8644cc7ccb2ec7a4a7cd67f648`.

## Dữ liệu và bất biến

Sinh bằng `python scripts/sft_cases.py generate --out <thư_mục>` với seed mặc định:

| Tệp | Số dòng | SHA256 |
|---|---:|---|
| `cases_sft_v1.jsonl` | 1.380 | `56d47a64908b37f2ec7ded513fca80ba1f81ce64f9ac2cbc74e064a24c44a11e` |
| `briefs_sft_v1.jsonl` | 1.646 | `ed8b290b9d251297fd2d7fa66d49cf16bfd10ac41013e09118dc4cbfd3fff3a4` |

- 1.406 phiếu đầu trùng từng byte với v4 sinh tại `084b39b`; SHA256 phần này:
  `068480e623e15374ea18ede4c4cd816537a4baf3343d610a2c0e73db84e7cd48`.
- 1.200 ca đầu giữ id, thứ tự, user, case_setup, customer và mã đơn. Ngoài bốn khung A,
  giữ nguyên từng byte. Bốn khung A chỉ đổi expect/fake_model/final_state, với ngoại lệ owner
  duyệt trong chat: **đúng 12 ca hotline được thêm knowledge của store_hours_contact.md**.
  Runner `--knowledge real` dùng KB thật, nên ngoại lệ này không đổi đầu vào lượt chạy thật.
- T14 đứng sau toàn bộ khung cũ; RNG của khung cũ không đổi. Test ghim hash phần ngoài A,
  phần bất biến của bốn khung A và danh sách id cũ.
- 180 ca T14 có 240 phiếu mới cần Glimmer viết: [danh sách đủ brief_id](brief_ids_T14.txt).
  Trường user trong ca T14 để trống. Khi kiểm fake, bản sao trong bộ nhớ dùng mã định danh
  làm đầu vào giao thức; không sinh lời khách, không ghi lại vào ca xuất ra hay đệm lời khách.
- Test chống trùng giá trị giả bộ đo chạy trên cả 1.380 ca và 1.646 phiếu.

## A–F và CLI cuối cùng

**A — Thước.** Hotline/VAT không chuyển; phàn nàn lặp lại bắt buộc chuyển;
khách bực lần đầu phải tra đơn, chuyển tùy model. HANDOFF_EITHER chỉ còn T12 xin Zalo và
T07 ngôn ngữ gay gắt. Chấm lại chỉ tính chuyển thành công khi status=ok; thiếu status giữ
cách cũ và gắn handoff_status_unknown. Kiểm: `test_w673_cases_rails.py`, hồi quy ruler/regrade.

**B — T14.** 18 khung × 10 ca; mỗi phiếu rail_pass=true. T14 thuộc EASY_TIGHT, ngoài HARD_SUITES.
Theo làm rõ của owner: #10 chọn lịch sử không liên lạc/không nghe máy, hiện returned/delivery_failed;
#11 chọn cùng loại lịch sử nhưng đã delivered. Sắp ổn định theo external_order_id.
`sft_dataset` nhận id T14, kiểm cấu trúc qua hợp đồng S07 trong bản sao; không sửa hợp đồng bộ đo.

**C — Lọt rào.** Brief mặc định không xuất khóa rail_pass. Khi bật, fill và verify dùng chung
validate_utterance gọi safety_gate; lý do trượt chứa tên rào. Kiểm đủ ba rào và phiếu không bật cờ.

**D — Phiếu đỡ và proxy.** Không điền nội dung goi_y. Các CLI:

```text
python scripts/sft_hints.py export --scores scores.json --adjudicated adj.json --cases cases.jsonl --out sheet.csv
python scripts/sft_hints.py export --scores scores.json --adjudicated adj.json --cases cases.jsonl --out per_case.csv --per-case-templates <khung_T11_draft>
python scripts/sft_hints.py import --csv sheet.csv --out hints.jsonl --check-only
python scripts/sft_hints.py import --csv sheet.csv --out hints.jsonl
python scripts/sft_hint_proxy.py --listen 127.0.0.1:8002 --upstream http://127.0.0.1:8001 --cases cases_filled.jsonl --hints hints.jsonl --log hint_log.jsonl --scopes scopes
python scripts/sft_select.py score --cases cases_filled.jsonl --runs runs.json --out scores.json
python scripts/sft_select.py score --cases cases_filled.jsonl --run-dir qwen=<thư_mục_run> --out scores.json
python scripts/sft_build.py --selection selection.json --cases cases_filled.jsonl --out-dir sft
```

- Mỗi mục runs.json có label, model, dir, run_offset, hinted, hint_log. Run không được trùng
  theo model giữa các thư mục. Vết được truy bằng số run gốc, ứng viên/chọn mẫu dùng số có offset.
- stale_input so trường user trong merged record với ca hiện tại. Bản ghi cũ thiếu trường user
  không bị kết luận stale chỉ dựa vào prompt đã định dạng/che dữ liệu.
- Gợi ý chỉ nối vào system đầu; không đổi tools, tin khác, tham số sinh. Authorization chuyển nguyên,
  không ghi log. Log chỉ metadata và hash. Proxy đa luồng, timeout mặc định 600 giây;
  HTTPS dùng kiểm chứng chỉ mặc định của urllib. Test dùng upstream HTTP cục bộ và transport HTTPS giả.
- Ưu tiên gợi ý: case_id+lượt → case_id+null → template+lượt → template+null.
  Lượt có gợi ý bị loại nếu nội dung/suy luận lộ nhãn; thiếu log khớp hash yêu cầu thì có hint_unverified.
- select cùng tier ưu tiên không gợi ý; đường chọn cũ khi không có gợi ý được kiểm hồi quy byte.
  Nhãn hinted/run_label/source_run chỉ thêm cho dạng --runs; đầu vào cũ giữ byte đầu ra cũ.
- build xuất meta.hinted và thống kê khi selection có nhãn hinted; gặp marker trong bất kỳ tin nào
  của mẫu thì dừng trước khi ghi dữ liệu, kể cả marker xuất hiện sau lớp phủ owner-edits.
- Theo bổ sung owner: sft_cjk export/import cũng đọc đúng các thư mục và run có offset.
  Chấm/chọn, CJK và build dùng chung load_mapped_trace_calls, không tự viết lại ánh xạ.
  Mã mẫu/lớp phủ dùng run sau offset. Test cho run thường 1–4 và run gợi ý 5–8 có chữ Hán khác nhau
  xác nhận export, kiểm đoạn gốc khi import và áp lớp phủ trong build đúng từng run;
  CSV/lớp phủ của scores cũ trùng từng byte với trước W6.7.3.
- CSV UTF-8 BOM, không ghi đè, goi_y trống khi export. Import chặn mã ngoài phạm vi,
  số tiền, marker và trùng 5-gram bộ đo. Theo bổ sung của owner: giới hạn 800 ký tự theo khung,
  1.200 theo ca; dòng theo ca được nhắc các mã đơn của chính ca đã xuất trong order_codes.

**Định tuyến T11 theo scope (bổ sung của owner).** Ứng dụng gửi tin user qua
format_case_assist_user_prompt: `[Chế độ: ...] ...`. Trên ca sinh hiện tại, endpoint không scope có
144/190 lượt T11 trùng tin operator (84 draft, 45 summary, 15 ask); proxy giữ no_hint khi khớp nhiều ca.
Giải pháp đã thêm: `--scopes DIR`, mỗi `<scope>.txt` chứa case_id, mỗi dòng một mã.
Proxy nhận và gỡ `/s/<scope>` trước khi chuyển các đường `/health`, `/v1/models`, `/v1/chat/completions`.
Chỉ khớp ca trong scope; scope một ca/một lượt dùng luôn ca đó khi câu user không phân biệt được.
Với ca nhiều lượt vẫn cần nhận diện lượt, không tự đoán. Scope lạ trả 404.
Notebook đợt dữ liệu có thể chạy shard T11 riêng từng ca với:
`--endpoint http://127.0.0.1:8002/s/<case_id>/v1/chat/completions`.
Không sửa runner; không gọi model để thử.

**E — Tỉ trọng.** T11 ra khỏi HARD_SUITES; mẫu thứ hai chỉ qua luật Tier S 1/2/5 của chính ca đó.
Trần mặc định tắt:

```text
python scripts/sft_select.py select --scores scores.json --adjudicated adj.json --out selection.json --suite-cap T11=0.12 --mode-cap T11:summary=0.25,T11:ask=0.45
```

Trần bộ tính trên tổng số mẫu/lượt sau bỏ lượt rào; trần chế độ tính trong bộ tương ứng.
Cắt sau trần khung và DeepSeek, ưu tiên mẫu thứ hai ở chế độ vượt trần, rồi mẫu chính rank thấp và băm seed.
Không bỏ draft, không thêm mẫu khác bù vào. Báo cáo số bỏ theo bộ × chế độ × vai và trần còn vượt do bảo vệ draft.

**F — Owner edits (bổ sung của owner).** `sft_build --owner-edits edits.jsonl` bỏ qua dòng của
run không có trong selection, liệt kê đầy đủ trong unused_owner_edits của stats/report.
Dòng thuộc run được chọn mà không áp được vẫn dừng lỗi trước khi ghi. Có test riêng cho hai trường hợp,
đồng thời cập nhật kỳ vọng W6.7.2 tương ứng.

## Đơn fixture T14

Mỗi khung dùng 10 đơn khác nhau, không khung nào phải dùng lại đơn (trần thực tế 1 lần/đơn/khung).
Riêng tập đủ điều kiện của #10 là 11 đơn, #11 là 12 đơn; lấy 10 đơn đầu theo thứ tự ổn định.

| Khung | Đơn dùng | Số lần cao nhất/đơn |
|---|---:|---:|
| t14_doi_nguoi_khong_dau | 10 | 1 |
| t14_doi_nguoi_vong_vo | 10 | 1 |
| t14_bot_khong_hieu_doi_nguoi | 10 | 1 |
| t14_doa_khieu_nai_san | 10 | 1 |
| t14_doa_kien | 10 | 1 |
| t14_doa_dang_bai_khac_tu | 10 | 1 |
| t14_doi_dia_chi_giao | 10 | 1 |
| t14_doi_nguoi_nhan | 10 | 1 |
| t14_khoi_phuc_don_huy | 10 | 1 |
| t14_khieu_nai_shipper_nho_xu_ly | 10 | 1 |
| t14_khieu_nai_shipper_chi_phan_anh | 10 | 1 |
| t14_hoi_roi_doi_nguoi | 10 | 1 |
| t14_chuyen_nha_doi_dia_chi | 10 | 1 |
| t14_hoi_gio_lam_viec | 10 | 1 |
| t14_nhac_shipper_hoi_don | 10 | 1 |
| t14_khen_nhan_vien_roi_hoi | 10 | 1 |
| t14_buc_lan_dau_hoi_don | 10 | 1 |
| t14_buc_don_co_van_de | 10 | 1 |

## Tệp đổi

- scripts: sft_cases.py, sft_dataset.py, eval_regrade.py, sft_utterances.py,
  sft_select.py, sft_build.py, sft_cjk.py, sft_hint_proxy.py (mới), sft_hints.py (mới).
- scripts/sft_templates: base.py, __init__.py, t14_handoff.py (mới).
- tests mới: test_w673_cases_rails.py, test_w673_proxy_hints.py, test_w673_select_build.py.
- tests cập nhật: test_w670_sft_fixture_cases.py (SHA/số lượng),
  test_w670_ruler_calibration.py (khung còn tự do), test_w672_select_build_cjk.py (mục F).
- notebooks/colab_agent.ipynb: dựng lại bằng build_agent_notebook.py.
- Báo cáo này và brief_ids_T14.txt.

Không sửa thư mục bàn giao, evals/suites, agent_protocol.py, retailops hay runner.
Không viết lời khách/nội dung gợi ý, không chạy model/API thật, Colab, Drive hay ổ E:.
Không mở PR/form PR, không merge, không push main.

## Kết quả kiểm

| Lệnh/nhóm kiểm | Kết quả cuối |
|---|---|
| `unittest discover -s tests -p "test_w673_*.py"` | 16/16 qua sau bổ sung CJK |
| `unittest discover -s tests -p "test_w672_*.py"` | 11/11 qua |
| Nhóm bảy module hồi quy ở 04 | 64 test qua, 1 test PDF bỏ qua vì thiếu pypdfium2 |
| `sft_cases generate` rồi `sft_cases check` | 1.380 ca, 1.646 phiếu; check 1.380/1.380 qua |
| `build_agent_notebook.py`, `--check`, `test_audit_remediation` | Dựng lại; đồng bộ; 10/10 test qua |
| `check_docs_contract.py` | Qua cả bốn mục |
| `git diff --check` và rà tệp cấm | Qua; không tệp cấm/thư mục bàn giao nào đổi |
| Bộ đầy đủ tại checkout chính | 1.386 test, 3 failures + 3 errors, 90 skipped; gồm 5 lỗi Windows cũ và 1 lỗi môi trường bên dưới |
| Test cách ly riêng tại worktree sạch, commit 91f5faa | Qua 1/1 |
| Bộ đầy đủ tại worktree sạch, commit 91f5faa | 1.387 test trong 677,963 giây; chỉ 2 failures + 3 errors có sẵn, 90 skipped; không lỗi W6.7.3 |

Chênh một test giữa hai lượt vì test CJK với --runs được bổ sung sau khi khởi động lượt checkout chính;
worktree sạch chạy toàn bộ bản mã cuối tại 91f5faa. Nhật ký và bộ ca sinh thử được giữ cục bộ trong
`artifacts/w673_thuc_thi_20261119/`, không đưa dữ liệu sinh thử lên nhánh.

Năm lỗi Windows có sẵn: `test_r1_w4_agent_scenarios` ×2,
`test_r1_w4_media_pipeline` ×1, `test_r1_w4_customer_ref_and_v8` ×2.
Lỗi thứ sáu tại checkout chính:
`test_marketplace_sim_stories_and_send.MarketplaceSimIsolationTests.test_item10_package_isolation_and_image_exclusion`,
do test quét checkout phụ có sẵn tại `.claude/worktrees/cai-nay-la-sao-bddcef/`.
Owner chọn giữ nguyên test, kiểm bằng worktree sạch ở ngoài repo; không đụng checkout phụ.
Worktree sạch do ứng dụng quản lý tại `C:\Users\HP\.codex\worktrees\w673-clean\CSKH_ban_le`,
detached ở đúng commit mã nêu trên; đã dọn bằng `git worktree remove` sau khi xác nhận đường dẫn,
đúng HEAD và không có thay đổi. Công cụ archive của ứng dụng từ chối vì coi đây là checkout chính của chat.

Các khác biệt so với 03 đều do owner bổ sung trong chat: chọn đơn theo lịch sử vận đơn cho #10/#11;
ngoại lệ knowledge của 12 ca hotline; định tuyến scope và giới hạn 1.200 ký tự cho gợi ý theo ca;
tương thích CJK với --runs; mục F bỏ qua lớp phủ của run ngoài selection;
chấp nhận lỗi môi trường thứ sáu tại checkout chính và đối chiếu bằng worktree sạch.
