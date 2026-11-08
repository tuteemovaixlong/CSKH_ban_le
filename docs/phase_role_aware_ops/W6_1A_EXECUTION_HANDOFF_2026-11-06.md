# Phase R1 — W6.1a Execution Handoff: sàn ảo và hợp đồng sự kiện

> **Trạng thái:** prompt thực thi do owner phát hành ngày 2026-11-06. Đây là module đầu tiên của W6 theo [W6 backlog](W6_BACKLOG_2026-11-06.md) mục 4. Không mở W6.1b trở đi.
> **Quyết định áp dụng:** [§19](W0_OWNER_DECISION_DELTA_2026-10-29.md#19-w61a-owner-decisions-2026-11-06), gồm W6.1a-D11 đến D14 bổ sung ngày 2026-11-07 về người nhận, thời hạn giao, voucher bồi thường giao trễ, và W6.1a-D15, D16 bổ sung cùng ngày sau lượt kiểm chứng PR #72. Thiết kế dữ liệu phía RetailOps để nhận các sự kiện này nằm ở [tài liệu database mục B](../../khoa_luan/07_co_so_du_lieu.md); W6.1a **không** làm phần đó.
> **Readiness:** W6.1a chỉ thêm một package độc lập, không đổi code, schema hay cấu hình của RetailOps, không deploy, nên không cần review readiness riêng; lượt kiểm chứng sau báo cáo là đủ.
> **Nguyên tắc:** sàn ảo là **hệ thống nguồn** đóng vai sàn thương mại điện tử, hãng vận chuyển và cổng thanh toán. Nó không chạm vào tiền, không chứa dữ liệu cá nhân thật, và chỉ nói chuyện với RetailOps qua sự kiện. Gặp quyết định chính sách chưa có trong tài liệu thì **dừng và hỏi owner**.

## 1. Mục tiêu làm việc

- Nhánh mới từ `origin/main`; không commit thẳng vào `main`.
- Chỉ thêm package `marketplace_sim/`, test trong `tests/test_marketplace_sim_*.py`, và một dòng `.marketplace_sim/` trong `.gitignore`. **Không sửa** file nào trong `retailops/`, `scripts/`, `web/`, `deploy/`, `data/`, `notebooks/`, `agent_protocol.py`, `retailops_*.py`. Ngoại lệ duy nhất theo W6.1a-D15: sửa `scripts/build_agent_notebook.py` để không nhúng `tests/test_marketplace_sim_*.py` vào notebook Colab; `notebooks/colab_agent.ipynb` giữ nguyên.
- Chỉ dùng thư viện chuẩn của Python 3.10 trở lên. Không thêm dependency.
- `marketplace_sim/` không được import bất kỳ module nào của RetailOps, và ngược lại.

## 2. Phạm vi và tiêu chí chấp nhận

| # | Việc phải làm | Tiêu chí chấp nhận, test cô lập |
|---|---|---|
| 0 | **Khung package và CLI.** `python -m marketplace_sim` với các lệnh: `init --data-dir DIR --seed N --merchant-id ID` tạo kho SQLite; `run --days N` sinh dữ liệu ngẫu nhiên có seed; `story NAME` chèn một kịch bản có tên; `advance --hours H` tua đồng hồ và phát các sự kiện đến hạn; `export --out FILE` xuất mọi sự kiện thành JSONL theo thứ tự `occurred_at`, rồi `event_id`; `ingest-requests --file PATH` đọc các yêu cầu phát voucher từ RetailOps, xem mục 11; `send --endpoint URL --secret-file PATH` gửi sự kiện chưa gửi; `status` in số sự kiện theo loại và trạng thái gửi. Thư mục dữ liệu mặc định là `.marketplace_sim/`. | Test gọi từng lệnh trên thư mục tạm; lệnh sai tham số trả mã lỗi khác 0 kèm thông báo tiếng Việt; không lệnh nào ghi ra ngoài `--data-dir` và `--out`. |
| 1 | **Hợp đồng sự kiện v2** đúng mục 3. Tạo `marketplace_sim/contract.py` để kiểm một sự kiện, `marketplace_sim/CONTRACT.md` chép nguyên mục 3, và `marketplace_sim/examples/` có một ví dụ hợp lệ cho mỗi loại sự kiện. | Mọi ví dụ và mọi sự kiện do sàn ảo sinh ra đều qua bộ kiểm; một bộ test lỗi cố ý cho từng trường bắt buộc, kiểu sai, giá trị ngoài tập cho phép, trường lạ, đều bị từ chối. |
| 2 | **Catalog.** Nạp sản phẩm và biến thể từ `marketplace_sim/data/catalog.json`: chép tên, nhóm, giá, bảo hành, chất liệu, mô tả từ `data/products.json` của RetailOps, và biến thể cùng tồn kho từ bảng ở `khoa_luan/eval_pack/03_HE_THONG_VA_DU_LIEU.md` mục 4.3, vì tồn kho từng biến thể không nằm trong `data/products.json`. Đây là file riêng của sàn ảo. Mỗi biến thể có **SKU duy nhất**. Với P-101, P-102, P-202, điền mô tả, chất liệu, cách giặt đúng nội dung ở bảng dưới đây. | Mỗi sản phẩm phát đúng một `product.upserted` khi khởi tạo; SKU không trùng; 3 sản phẩm trên có đủ ba trường như bảng; không có trường nào nhắc tới dữ liệu thử nghiệm. |
| 3 | **Khách và người nhận.** Sinh khách với mã `SIM-C-` và số thứ tự, tên hiển thị lấy từ danh sách tên giả lập cố định trong package; hồ sơ khách không có thông tin liên hệ. Thông tin người nhận chỉ nằm trong `order.created`: tên lấy từ danh sách giả lập; số điện thoại 10 chữ số bắt đầu bằng tiền tố cố định `phone_prefix` khai báo trong `params.json`, mặc định `0123`, ghi chú là số giả lập; địa chỉ ghép từ danh sách mẫu trong package gồm số nhà, tên đường, phường hoặc xã, quận hoặc huyện, tỉnh hoặc thành phố. Không có email. | Mọi `customer.upserted` chỉ có các trường ở mục 3; test quét toàn bộ file xuất: số điện thoại đầy đủ chỉ xuất hiện ở `recipient.phone` và luôn bắt đầu bằng `phone_prefix`; không có địa chỉ email; địa chỉ chỉ xuất hiện trong `recipient`. |
| 4 | **Đơn và thanh toán.** Mỗi đơn có `ordered_at`, `promised_delivery_by` tính theo khu vực giao và hãng, các dòng hàng theo SKU, tổng tiền, phí ship, phương thức thanh toán, người nhận theo mục 3. Đơn trả trước sinh `payment.updated` từ `payment_sim`; đơn COD sinh giao dịch thanh toán do hãng vận chuyển thu hộ khi giao thành công. Trạng thái đơn đi theo `pending` → `confirmed` → `shipping` → `delivered`, hoặc `cancelled` trước khi giao. | Test máy trạng thái: không có chuyển trạng thái nào ngoài danh sách; `total` bằng tổng dòng hàng cộng phí ship; đơn COD chỉ có thanh toán thành công khi đã giao; `promised_delivery_by` luôn sau `ordered_at`. |
| 5 | **Vận chuyển.** Ba hãng mô phỏng, cấu hình trong `marketplace_sim/data/carriers.json`: hãng mô phỏng theo GHN dùng bộ mã công khai `ready_to_pick`, `picking`, `picked`, `storing`, `transporting`, `sorting`, `delivering`, `delivered`, `delivery_fail`, `waiting_to_return`, `return`, `returned`, `cancel`; hai hãng còn lại dùng bộ mã giả lập, ghi rõ trong file là giả lập. Mỗi lần giao thất bại có lý do, tối đa 3 lần rồi chuyển hoàn. Mỗi `shipment.updated` có `sequence` tăng dần theo vận đơn, cùng bưu cục hoặc kho, quận, tỉnh của mốc đó, và dự kiến giao mới nhất. | Test: không sự kiện nào làm vận đơn đi lùi; sau 3 lần thất bại chỉ còn nhánh hoàn; `delivered` của vận đơn trùng thời điểm đơn chuyển `delivered`; số điện thoại shipper luôn ở dạng đã che. |
| 6 | **Hoàn tiền.** `refund.updated` từ `payment_sim` với trạng thái gốc, số tiền không vượt số đã thu, kênh hoàn. Đơn COD hoàn qua chuyển khoản. | Test: tổng hoàn của một đơn không vượt số đã thu; trạng thái hoàn không đi lùi; mỗi hoàn tiền nối đúng giao dịch thanh toán, trừ đơn COD. |
| 7 | **13 kịch bản có tên**, xem danh sách dưới đây. Mỗi kịch bản tạo một đơn với mốc thời gian cố định tương đối so với đồng hồ, để bộ đánh giá dùng làm fixture. | Mỗi kịch bản chạy hai lần trên hai kho mới cho ra cùng chuỗi sự kiện; trạng thái cuối của đơn, vận đơn, thanh toán, hoàn tiền đúng như mô tả. |
| 8 | **Tất định và tham số.** Đồng hồ bắt đầu ở `2026-10-01T08:00:00+07:00` trong chế độ tất định. Tham số tỉ lệ nằm trong `marketplace_sim/data/params.json`, mỗi tham số có trường `note` ghi "giả định". | Cùng seed và cấu hình thì `export` cho file giống hệt từng byte; đổi seed thì khác; không dùng thời gian thật của máy trong chế độ tất định. |
| 9 | **Gửi sự kiện.** `send` POST từng sự kiện với header ở mục 3; 2xx hoặc 409 coi là đã nhận; lỗi khác thử lại sau 1, 2, 4, 8, 16 giây, quá 5 lần thì đánh dấu `dead`. Chỉ gửi tới `localhost`, `127.0.0.1`, `::1` hoặc tên host không có dấu chấm, như tên service trong mạng Docker; host khác bị từ chối. Đọc khóa từ `--secret-file`, không in khóa ra màn hình hay log. | Test với một HTTP server tạm trên loopback trong test: chữ ký kiểm lại được bằng khóa test; gửi lại không tạo bản nhận mới; host công khai bị từ chối; khóa không xuất hiện trong output. |
| 10 | **Cách ly.** | Test quét AST: không file nào trong `marketplace_sim/` import `retailops`, `agent_protocol` hay `retailops_*`; không file nào ngoài `marketplace_sim/` và `tests/` import `marketplace_sim`. `check_deployment_contract.py` vẫn đạt; package không có trong image. |
| 11 | **Voucher bồi thường.** `ingest-requests --file PATH` đọc file JSONL các yêu cầu `voucher.requested` từ RetailOps theo mục 3; với mỗi yêu cầu hợp lệ chưa xử lý, sàn ảo tạo mã voucher và phát `voucher.issued` có `request_ref` bằng `request_id` của yêu cầu. Yêu cầu lặp lại không tạo mã mới. Mã voucher là chuỗi ngẫu nhiên theo seed, không đoán được từ mã đơn. | Test: một yêu cầu cho đúng một `voucher.issued`; đọc lại cùng file không phát thêm; yêu cầu sai hợp đồng bị bỏ qua và ghi lỗi; mệnh giá và loại voucher đúng như yêu cầu. |

**Nội dung 3 sản phẩm, W6.1a-D10:**

| Mã | Mô tả | Chất liệu | Cách giặt |
|---|---|---|---|
| P-101 Áo thun Essential | Áo thun cổ tròn, form regular, vải dày vừa, mặc hằng ngày. | 100% cotton, định lượng 220 g/m² | Giặt máy nước lạnh dưới 30°C, lộn trái khi giặt, không dùng chất tẩy, phơi nơi thoáng mát, ủi nhiệt độ thấp. |
| P-102 Áo khoác Everyday | Áo khoác dáng suông có mũ, khóa kéo YKK, hai túi khóa kéo, chống gió và chống nước nhẹ. | Vải dù polyester 2 lớp, lót lưới | Giặt tay hoặc giặt máy chế độ nhẹ, kéo khóa trước khi giặt, không sấy nhiệt cao, không ủi trực tiếp lên lớp phủ. |
| P-202 Áo polo | Áo polo cổ bẻ, tay ngắn, vải cá sấu thoáng khí. | Vải cá sấu 65% cotton, 35% polyester | Giặt máy nước lạnh, không vắt mạnh, phơi ngang để giữ form cổ. |

**13 kịch bản có tên:**

| Tên | Tình huống | Trạng thái cuối |
|---|---|---|
| `giao_dung_han_cod` | đơn COD giao thành công sau 3 ngày | đơn `delivered`, thanh toán thu hộ thành công |
| `dang_trung_chuyen` | đơn trả trước đang trên xe liên tỉnh | đơn `shipping`, vận đơn `transporting` |
| `cap_nhat_ao_giao_lai` | shipper báo không liên lạc được, giao lại thành công trong ngày | 1 lần `delivery_fail`, cuối cùng `delivered` |
| `giao_that_bai_hoan_ve` | 3 lần giao thất bại rồi chuyển hoàn | vận đơn `returned`, đơn `cancelled` |
| `nghen_kho_mega_sale` | đơn đợt Mega Sale, kẹt ở kho phân loại hơn 48 giờ; mốc tương đối theo W6.1a-D16, "11.11" chỉ là nhãn tình huống | vận đơn `sorting` quá 48 giờ |
| `hoan_tien_cham` | trả hàng được duyệt, hoàn tiền còn `processing` sau 10 ngày | hoàn tiền chưa xong |
| `hoan_tien_that_bai` | hoàn về ví bị lỗi | hoàn tiền thất bại có lý do |
| `thanh_toan_that_bai_roi_thanh_cong` | chuyển khoản lần đầu lỗi, lần hai thành công | 2 giao dịch, giao dịch sau thành công |
| `huy_truoc_khi_giao` | khách hủy khi đơn còn `confirmed` | đơn `cancelled`, không có vận đơn giao |
| `doi_size_trong_han` | giao thành công 5 ngày trước | đơn `delivered` |
| `qua_han_doi_tra` | giao thành công 20 ngày trước, quá 7 và 15 ngày, còn trong 90 ngày | đơn `delivered` |
| `het_bao_hanh` | giao thành công 100 ngày trước | đơn `delivered` |
| `giao_tre_han_cam_ket` | giao thành công 3 ngày sau `promised_delivery_by` | đơn `delivered`, `delivered_at` muộn hơn thời hạn cam kết 72 giờ |

## 3. Hợp đồng sự kiện v2

**Phong bì chung**, mọi trường đều bắt buộc trừ khi ghi khác:

| Trường | Kiểu | Quy tắc |
|---|---|---|
| `contract` | string | luôn `retailops-integration-v2` |
| `event_id` | string | duy nhất trong một `source_system`, mẫu `[A-Za-z0-9._:-]{8,128}` |
| `event_type` | string | một trong 8 loại sự kiện hoặc loại yêu cầu dưới đây |
| `source_system` | string | `marketplace_sim` hoặc `payment_sim`; yêu cầu từ RetailOps dùng `retailops` |
| `merchant_id` | string | mã cửa hàng phía sàn; RetailOps tự ánh xạ sang cửa hàng của mình |
| `occurred_at` | string | ISO-8601 có múi giờ `+07:00` |
| `sequence` | integer | tăng dần trong một đối tượng: một sản phẩm, đơn, vận đơn, giao dịch hoặc hoàn tiền |
| `data` | object | theo loại sự kiện; không chấp nhận trường lạ |

**Loại sự kiện và `data`:**

| `event_type` | Nguồn | Trường trong `data` |
|---|---|---|
| `product.upserted` | `marketplace_sim` | `external_product_id`, `title`, `category`, `price`, `description`, `material`, `care`, `warranty_days`, `variants` là danh sách gồm `sku`, `variant_name`, `size`, `color`, `price`, `stock`. Trường không có giá trị thì là `null`. |
| `customer.upserted` | `marketplace_sim` | `external_customer_id`, `display_name`. Không có trường liên hệ nào khác. |
| `order.created` | `marketplace_sim` | `external_order_id`, `external_customer_id`, `ordered_at`, `items` gồm `sku`, `external_product_id`, `title`, `variant_name`, `quantity`, `unit_price`; `shipping_fee`, `total`, `currency` là `VND`, `payment_method` là `cod`, `bank_transfer`, `e_wallet` hoặc `card`; `promised_delivery_by`; `recipient` gồm `name`, `phone`, `address_line`, `ward`, `district`, `province` |
| `order.status_changed` | `marketplace_sim` | `external_order_id`, `status` là `pending`, `confirmed`, `shipping`, `delivered` hoặc `cancelled`; `reason` có thể `null` |
| `shipment.updated` | `marketplace_sim` | `external_shipment_id`, `external_order_id`, `carrier`, `tracking_code`, `carrier_status_raw`, `hub_name` có thể `null`, `district`, `province`, `description`, `fail_reason` có thể `null`, `shipper_name` có thể `null`, `shipper_phone_masked` có thể `null`, `estimated_delivery_at` có thể `null`, `delivery_attempts` |
| `payment.updated` | `payment_sim` với đơn trả trước; `marketplace_sim` với tiền COD do hãng vận chuyển thu hộ | `provider`, `provider_txn_ref`, `external_order_id`, `method`, `amount`, `provider_status_raw`, `settled_at` có thể `null` |
| `refund.updated` | `payment_sim` | `provider`, `provider_refund_ref`, `provider_txn_ref` có thể `null` với đơn COD, `external_order_id`, `amount`, `channel` là `original_method`, `bank_transfer` hoặc `e_wallet`; `provider_status_raw`, `failure_reason` có thể `null`, `initiated_at`, `completed_at` có thể `null` |
| `voucher.issued` | `marketplace_sim` | `external_voucher_id`, `code`, `voucher_type` là `amount` hoặc `free_shipping`, `value` là số tiền VND, bằng 0 với `free_shipping`; `valid_until`, `external_order_id`, `external_customer_id`, `request_ref` có thể `null` khi sàn tự phát |

**Yêu cầu từ RetailOps gửi sàn**, cùng phong bì, `source_system` là `retailops`, đọc từ file JSONL ở W6.1a; đường gửi thật thuộc W6.1b:

| `event_type` | Trường trong `data` |
|---|---|
| `voucher.requested` | `request_id`, `external_order_id`, `external_customer_id`, `voucher_type`, `value`, `reason` là `late_delivery`, `approved_by_role` là `staff` hoặc `manager` |

Số tiền là số nguyên VND, từ 0 đến 10^12. Chuỗi văn bản tối đa 500 ký tự. Thông tin người nhận chỉ được xuất hiện trong `order.created`; RetailOps lưu và bảo vệ theo W6.1a-D11. Sàn ảo **chỉ phát mã trạng thái gốc**; ánh xạ sang trạng thái chuẩn của RetailOps là việc của connector ở W6.1b.

**Gửi qua HTTP:** `POST` thân là đúng một phong bì JSON UTF-8, kèm header:

- `X-Sim-Event-Id`: bằng `event_id`;
- `X-Sim-Timestamp`: giây Unix lúc gửi;
- `X-Sim-Signature`: `v1=` cộng chuỗi hex của HMAC-SHA256 với khóa của connector, trên chuỗi `timestamp` + `.` + thân thô.

Phía nhận từ chối khi timestamp lệch quá 300 giây. Phần nhận thuộc W6.1b.

## 4. Ngoài phạm vi

- Mọi thay đổi phía RetailOps: migration v9, endpoint nhận sự kiện, connector, adapter, tool, seed. Đây là W6.1b.
- Mô phỏng định dạng riêng của một cổng thanh toán thật; giao diện web cho sàn ảo; connector CSV; connector của nền tảng thật.
- Phía RetailOps của voucher và thông báo chủ động: phát hiện trễ hạn, đề xuất, duyệt, gửi yêu cầu, lưu voucher, thông báo cho khách. Đây là W6.1b.
- Đưa sàn ảo vào image hoặc chạy trên EC2.

## 5. Kiểm tra và báo cáo

Chạy và báo đúng số pass, fail, skip: `python -m unittest discover -s tests -q`; test JS theo `.github/workflows/ci.yml` bằng Node thật; `python scripts/check_docs_contract.py`; `python scripts/check_deployment_contract.py`; `python scripts/check_eval_dataset.py`; `git diff --check`. Chạy thêm `python -m marketplace_sim` theo trình tự `init`, `run --days 30`, đủ 13 `story`, `ingest-requests` với một file yêu cầu mẫu, `export` hai lần trên hai kho mới, rồi so hai file xuất bằng SHA-256.

Báo cáo gồm: file thêm theo từng mục 0–11; kết quả từng lệnh; SHA-256 của file xuất; DONE hoặc BLOCKED từng mục; URL PR và kết quả CI. Thêm một dòng mới vào cột của bạn trong [W1 execution log](W1_EXECUTION_LOG_2026-10-31.md), ghi rõ là W6.1a, không sửa dòng cũ.

**Cấm:** merge; push vào `main`; force-push, rebase, reset, stash; đổi variable hoặc secret của repo; chạy workflow deploy hoặc live-e2e; truy cập EC2, SSM, DB production, Colab hoặc LLM thật, dữ liệu khách hàng; gửi sự kiện tới host nào ngoài loopback; sửa file nằm ngoài phạm vi ở mục 1.

## 6. Sau khi báo cáo

Chỉ chạy **một** lượt kiểm chứng theo tiêu chí ở mục 2. Owner quyết định merge. W6.1a không đổi image nên không deploy.
