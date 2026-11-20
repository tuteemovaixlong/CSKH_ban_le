# Sửa CI PR #135 — Test hồi quy không cần lịch sử Git

Nhánh: `phase-r1-w6-7-3-khung-do`.
Commit mã được kiểm trong clone nông: `393f05281a0e3cb905a5ee10c1c60534ede46f1a`.
SHA đầu nhánh sau khi đẩy báo cáo được ghi trong tin bàn giao.

## Thay đổi

Năm test lỗi ở CI gọi baseline_module()/baseline(), tải mã cũ bằng git show.
Checkout nông không có các commit mốc nên các lời gọi này thất bại với exit 128.

Đã chạy một lượt lấy đầu ra giả từ mã mốc trên checkout có lịch sử:
- Nhóm pipeline/CJK: `0780af0207c858c993e6d745923feb000bdf1e4d`.
- Nhóm G: `0f21789f1a37dd99d38dc31d46fd3e930e6c3c85`.

SHA256 của 11 nhóm đầu ra (19 tệp) được ghim trong `tests/w673_regression_pins.py`.
Test hiện chỉ chạy mã hiện tại và so với các giá trị này; không tải/chạy mã lịch sử,
không gọi Git, không fetch thêm commit và không thêm skip.
Các kiểm tra run 1–8, lớp phủ, loại ca theo danh sách và nội dung báo cáo được giữ nguyên.

Để cùng pin dùng trên Windows/Linux, chỉ chuẩn hóa CRLF thành LF và đường dẫn JSON
nằm trong workspace tạm thành `<WORKSPACE>/...`. Giữ nguyên nội dung, thứ tự, trường,
nhãn, thống kê và định dạng khác. Có test xác nhận đổi nội dung/định dạng vẫn làm lệch hash.
Fixture là module Python để được đóng gói theo quy tắc tests/*.py hiện có.

## Tệp đổi

- tests/test_w673_select_build.py: pin cho scores, export vòng 1/2, import, select, build, CJK export/import;
  thêm test kiểm phạm vi chuẩn hóa.
- tests/test_w673_stale_eval_values.py: pin cho scores --runs, scores --run-dir và đầu ra build dữ liệu giả cũ.
- tests/w673_regression_pins.py: helper và SHA256 mốc, không có bộ sinh pin chạy trong test.
- notebooks/colab_agent.ipynb: dựng lại sau khi đổi test.
- Báo cáo này và các liên kết từ báo cáo trước.

Không sửa workflow CI, scripts công cụ/ứng dụng, runner, system prompt, evals/suites,
khung ca/phiếu hay thư mục bàn giao. Không viết lời khách/nội dung gợi ý, không gọi model.

## Kiểm trong clone nông

Clone từ chính nhánh đã commit qua giao thức file, có áp dụng --depth 1:

```text
git -c core.longpaths=true clone --depth 1 --single-branch --branch phase-r1-w6-7-3-khung-do <URI_file_cua_checkout_goc> <thu_muc_clone>
```

Đã xác nhận bằng Git:
- rev-parse --is-shallow-repository = true.
- rev-list --count HEAD = 1.
- Hai commit mốc trên không tồn tại trong clone.
- HEAD đúng commit mã nêu ở đầu báo cáo.

| Lệnh trong clone | Kết quả |
|---|---|
| `unittest discover -s tests -p "test_w673_*.py"` | 22/22 qua, không skip; 180/180 ca T14 qua gateway giả |
| `unittest discover -s tests -p "test_w672_*.py"` | 11/11 qua |
| Nhóm bảy module hồi quy SFT/regrade/cache/export/no_eval_values ở 04 | 64 test, không lỗi; 1 test PDF bỏ qua vì thiếu pypdfium2 |
| `build_agent_notebook.py --check` | Đồng bộ |
| `unittest tests.test_audit_remediation` | 10/10 qua |
| `check_docs_contract.py` | Qua cả bốn mục |

Clone kiểm và log được giữ cục bộ tại
`C:\Users\HP\.codex\visualizations\2026\11\19\01a1f486-6c5c-7f92-a70b-aee4b2575e41\w673_shallow_ci`,
trong `artifacts/shallow_ci/`. Các nhóm kiểm trên chỉ dùng dữ liệu giả.
Không chạy lại toàn bộ test ứng dụng ngoài các nhóm hồi quy yêu cầu; không trình bày
kết quả bộ đầy đủ ở lượt trước như kết quả CI sau lần sửa này. CI GitHub sẽ chạy lại khi push nhánh.
