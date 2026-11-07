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
