# Phase 5 — P5-B Google Test Identity Evidence

- **Baseline SHA (merged)**: `dd0947aad3a2dc8884710c8f6c609f42b67417bd` (PR #37)
- **Workstream**: `P5-B — Google test identity`
- **Scope**:
  - Map `(issuer, sub, verified_email)` → principal → tenant/customer link.
  - Loại bỏ hoàn toàn `ORDER BY id LIMIT 1` trong việc chọn tenant cho Google login.
  - Không dùng email đơn độc làm khóa; distinct sub luôn tạo distinct principal/customer.
  - Kiểm tra `/api/session`, `/api/profile` và cô lập đơn hàng (tenant/customer isolation).
  - Kiểm thử offline 100%, không lưu credential thật trong repository.
- **Trạng thái P5-B**: **PASS (ĐẠT)** — Sẵn sàng chuyển giao owner review.

---

## 1. Kết quả kiểm tra bộ Contracts & Linter

| ID | Contract / Lệnh | Kết quả | Chi tiết |
|---|---|:---:|---|
| **C1** | `python scripts/check_docs_contract.py` | **PASS** | 4/4 checks passed (Dataset integrity, Stale Git HEAD, Link & markdown rules, AST Dynamic tool contract). |
| **C2** | `python scripts/check_eval_dataset.py` | **PASS** | `baseline_v1.jsonl`: 30 cases OK; categories distribution đạt chuẩn. |
| **C3** | `python scripts/check_live_e2e_contract.py` | **PASS** | `LIVE_E2E_CONTRACT_OK`: cú pháp, packaging, không rò rỉ secret. |
| **C4** | `git diff --check` | **PASS** | Exit code 0, không có trailing whitespace hay conflict markers. |

---

## 2. Kết quả kiểm thử P5-B Offline Test Suite

File kiểm thử chuyên biệt: `tests/test_phase5_google_identity.py`

```text
Ran 12 tests in 1.465s — OK
```

| STT | Test Case | Tiêu chí nghiệm thu | Kết quả |
|---|---|---|:---:|
| 1 | `test_google_identity_mapping_issuer_sub_verified_email` | `(issuer, sub, verified_email)` map đúng `principal_id` và `customer_id`. Re-login với cùng `sub` giữ nguyên định danh. | **PASS** |
| 2 | `test_no_order_by_id_limit_1_refuses_ambiguous_tenant` | Khi có nhiều active tenant và chưa cấu hình tenant chỉ định, Google login từ chối đoán ngẫu nhiên (`503 ambiguous_tenant`), loại bỏ `ORDER BY id LIMIT 1`. Khi truyền `tenant_id` rõ ràng thì map chính xác. | **PASS** |
| 3 | `test_configured_demo_tenant_via_env_or_property` | Tenant demo cấu hình qua `default_tenant_id` hoặc env `RETAILOPS_DEMO_TENANT_ID` / `GOOGLE_AUTH_TENANT_ID` được resolve tất định. | **PASS** |
| 4 | `test_smoke_tenant_is_never_selected_as_google_fallback` | Tenant smoke/synthetic (`e2e-`, `smoke-`, `synthetic-`) không bao giờ bị chọn làm fallback cho Google login. | **PASS** |
| 5 | `test_email_never_used_as_sole_key` | Hai tài khoản Google có cùng email nhưng khác `sub` không bao giờ dùng chung principal hay customer. Không dùng email làm khóa độc lập. | **PASS** |
| 6 | `test_unverified_email_cannot_link_to_legacy_principal` | Email chưa verify (`email_verified=False`) tuyệt đối không được link vào tài khoản legacy hiện có. | **PASS** |
| 7 | `test_email_update_with_same_sub_preserves_principal_and_customer` | Khi người dùng đổi email trên Google nhưng giữ nguyên `sub`, hệ thống cập nhật email trong `external_identities` mà không làm thay đổi `principal_id` hay `customer_id`. | **PASS** |
| 8 | `test_external_identity_audit_events_recorded` | Các thao tác tạo mới và liên kết external identity đều ghi nhận sự kiện kiểm toán vào `identity_events`. | **PASS** |
| 9 | `test_api_session_profile_and_tenant_customer_isolation` | `/api/session` và `/api/profile` trả về đúng tenant/principal/customer/role; đơn hàng của Customer A1 không bị nhìn thấy bởi Customer A2 cùng tenant hoặc Customer B1 khác tenant. | **PASS** |
| 10 | `test_same_google_identity_across_tenants_gets_isolated_customers` | Cùng một Google principal khi đăng nhập Tenant 1 và Tenant 2 sẽ nhận hai `customer_id` độc lập theo tenant scope. | **PASS** |
| 11 | `test_live_mode_security_guards` | Ở `data_mode=live`, thiếu `sub` bị từ chối 400 `missing_sub`, và không seed sample orders. | **PASS** |
| 12 | `test_invalid_or_nonexistent_tenant_raises_error` | Đăng nhập chỉ định tenant không tồn tại hoặc không active sẽ trả lỗi 503 `tenant_unavailable`. | **PASS** |

---

## 3. Hồi quy các Test Suite liên quan

- `tests/test_auth_google.py`: 14/14 tests PASS (0.228s)
- `tests/test_live_e2e_isolation.py`: 3/3 tests PASS (0.013s)
- `tests/test_order_tool_recovery.py`: 37/37 tests PASS (4.590s)
- `tests/test_pr_a_correctness.py`: 56/56 tests PASS (7.833s)
- `tests/test_persistent_identity.py`, `tests/test_public_web.py`, `tests/test_business_api.py`: 50/50 tests PASS (17.671s)

---

## 4. Kiến trúc thay đổi cốt lõi

1. **`retailops/identity/persistent.py`**:
   - Thêm phương thức `resolve_google_tenant(sub, issuer, tenant_id)`.
   - Ưu tiên resolve: (1) `tenant_id` tham số gọi; (2) `self.default_tenant_id`; (3) biến môi trường `RETAILOPS_DEMO_TENANT_ID` / `GOOGLE_AUTH_TENANT_ID`; (4) membership đang hoạt động của identity `(issuer, sub)`; (5) tenant duy nhất nếu không phải tenant smoke.
   - Loại bỏ triệt để truy vấn `SELECT id FROM tenants WHERE active=1 ORDER BY id LIMIT 1`. Nếu có nhiều tenant mà không cấu hình chỉ định, hệ thống fail-closed với 503 `ambiguous_tenant`.
   - Bổ sung tham số `default_tenant_id` trong `PersistentSessions.__init__`.

2. **`retailops/identity/postgres.py`**:
   - Cập nhật `PostgresSessions.__init__` nhận `default_tenant_id` và đồng bộ với biến môi trường.

3. **`retailops/identity/store.py`**:
   - Cập nhật `external_identities.email` khi `email_verified=True` và email thay đổi nhưng cùng `sub`.
   - Ghi nhận `identity_events` kiểm toán (`external_identity_created`, `external_identity_linked`).
   - Bổ sung helper `external_identity(issuer, sub)` và `customer_link(tenant_id, principal_id)`.

4. **`retailops/config.py` & `retailops/bootstrap.py`**:
   - Thêm trường cấu hình `demo_tenant_id` vào `Settings` và đọc từ `RETAILOPS_DEMO_TENANT_ID` / `GOOGLE_AUTH_TENANT_ID`.
   - Truyền `default_tenant_id` khi khởi tạo session backend trong `build_public_app`.

5. **`retailops/http/auth_google.py` & `retailops/http/public.py` & `retailops/http/routes.py`**:
   - Trả `issuer` trong `exchange_code_for_user_info` và truyền tới `login_google`.
   - Đồng nhất xử lý `/api/profile` cùng `/api/session` để trả đầy đủ `tenant_id`, `principal_id`, `customer_id`, `name`, `role`.

---

## 5. Kết luận P5-B

Chặng P5-B (Google Test Identity & Tenant Isolation) **CHÍNH THỨC HOÀN THÀNH VÀ ĐẠT (PASS)** theo đúng các tiêu chí của `docs/phase5/PHASE_5_PLAN.md` và `docs/phase5/PHASE_5_EXECUTION_HANDOFF.md`.
Dừng tại đây để chờ owner review PR trước khi chuyển sang P5-C (Sales simulator & import contract).
