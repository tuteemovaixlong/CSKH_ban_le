# RetailOps — web hỗ trợ khách hàng bán lẻ trên EC2

**Quy trình sử dụng hiện tại: mở web HTTPS trên EC2. Không cần chạy localhost.**
VS Code dùng để sửa code và Git; GitHub Actions chạy CI/CD; EC2 chạy web/API/PostgreSQL; Colab chỉ phục vụ model khi chọn Custom. Dự án chỉ dùng dữ liệu giả lập.

## Bắt đầu ở đây

[Quy trình EC2: mở web, phát triển, test và dọn phần dư](docs/EC2_WEB_WORKFLOW.md).

Địa chỉ được xác minh ngày 2026-09-08: `https://retailops.54-221-116-13.sslip.io`.
Đây là snapshot, không phải domain cố định: sau stop/start EC2 phải đối chiếu IP và hai biến `RETAILOPS_PUBLIC_HOST` / `RETAILOPS_PUBLIC_ORIGIN` theo runbook.

Mở web trong trình duyệt và dùng tài khoản demo đã cấp. Không chạy `python retailops_api.py`, không tạo `RETAILOPS_DEMO_TOKEN` trên Windows và không dùng token local để đăng nhập EC2. Public web vẫn giữ credential/cookie, tenant, customer và quyền truy cập. PR #26 auto-login localhost đã đóng không merge.

Luồng nghiệp vụ: tra đơn → chọn lý do hủy → xem lại → xác nhận → lưu trạng thái và nhật ký. Model chỉ hỗ trợ hội thoại và công cụ đọc; backend kiểm tra quyền, chủ sở hữu, trạng thái, phiên bản, thời hạn và idempotency trước giao dịch.

## Bản đồ Tài liệu & Hệ thống

**Phase R1 (cập nhật 2026-10-30):** final docs/design `PASS` ngày 2026-10-26 và focused Argon `PASS` cho bản three-wave trước đó chỉ là kết quả lịch sử. Báo cáo Argon mới nhất được cung cấp là vòng 6: `CHANGES REQUIRED` (0 BLOCKER / 0 MAJOR / 2 MINOR); hai chỉnh sửa docs được ghi trong [review reconciliation và chronology chuẩn](docs/phase_role_aware_ops/W0_REVIEW_RECONCILIATION_2026-10-28.md). Không yêu cầu thêm vòng Argon cho các mục này. Implementation readiness vẫn `BLOCKED` theo review riêng do owner cung cấp (9 BLOCKER / 6 MAJOR / 3 MINOR); chỉ W0 read-only tiếp tục, W1–W6 chưa được phép bắt đầu. Delivery dự kiến theo nhóm `W0–W2`, `W3–W4`, `W5–W6`, tuần tự `W0 → W1 → W2 → W3 → W4 → W5 → W6`, không chạy song song; thứ tự trong hai cặp chưa được owner chốt. GitHub `main` chưa được xác minh mới trong lần cập nhật này: bằng chứng remote gần nhất được Argon ghi nhận là `2026-10-29T23:11:17+07:00`, SHA `bbfd11d0…`; không xem đó là xác nhận current main, deploy hay runtime. Xem [R1 design](docs/phase_role_aware_ops/README.md), [latest owner delta](docs/phase_role_aware_ops/W0_OWNER_DECISION_DELTA_2026-10-29.md), [W0 register](docs/phase_role_aware_ops/W0_BASELINE_AND_DECISION_REGISTER_2026-10-27.md), [W0 role inventory](docs/phase_role_aware_ops/W0_ROLE_INVENTORY_2026-10-29.md), [contract freeze/gap register](docs/phase_role_aware_ops/W0_CONTRACT_FREEZE_AND_GAP_REGISTER_2026-10-29.md), [review reconciliation](docs/phase_role_aware_ops/W0_REVIEW_RECONCILIATION_2026-10-28.md), and [blocked readiness](docs/phase_role_aware_ops/IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md). EC2 hiện do owner báo OFF; W0 không kiểm tra runtime.

**Cập nhật vận hành gần nhất (2026-10-24):** owner-pasted SSM/psql output báo đã xóa các target legacy order (`O-757461`, `O-819126`, cùng direct delete trước đó cho `O-847064`); xem [biên bản và giới hạn evidence](docs/04_OPERATIONS/ORDER_DATA_CLEANUP_2026-10-24.md). [PR #46](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/46) gỡ tự động seed đơn mẫu khi Google login đã merge vào `main` tại `146401f1831b81d5af4a110f6ddc06e50465b9a8` và deploy chính thức lên EC2 qua run [`40089312937`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40089312937) (`sha256:25193c65e52e7cf7ec41a3a366fa3f76d63c034f686232f405affa04cf1eab63`, đã xác minh read-only `GET /healthz`, `GET /` và `GET /app.js` trên `https://retailops.98-93-228-155.sslip.io`; bước đối chiếu trực quan bảng Orders trong phiên Chrome đã đăng nhập dành cho chủ dự án); xem [báo cáo thực thi](docs/phase5/DEMO_ORDER_SEEDING_REMEDIATION_HANDOFF_2026-10-24.md).

### 1. Hiện trạng Vận hành & Bằng chứng Kiểm thử (Ground Truth)

| Tài liệu | Nội dung |
| --- | --- |
| [CURRENT_PROJECT_STATUS](docs/CURRENT_PROJECT_STATUS.md) | **Hiện trạng hệ thống đầy đủ**: Bằng chứng kiểm thử L1–L4, đối chiếu tính năng thực tế vs tài liệu |
| [RELEASE_MANIFEST](docs/RELEASE_MANIFEST.md) | Tiêu chí nghiệm thu, ranh giới an toàn và quy trình phát hành |
| [BUSINESS_TEST_SCENARIOS](docs/BUSINESS_TEST_SCENARIOS.md) | Đặc tả 6 kịch bản SOP chuẩn (SPX, 1-1, size, Mega SOC, rage, human handoff) |

### 2. Kiến trúc Hệ thống Đang Hoạt động (Active Architecture)

| Phần | Tài liệu |
| --- | --- |
| Ranh giới module & Cấu hình nền tảng | [SYSTEM_FOUNDATION](docs/SYSTEM_FOUNDATION.md) |
| Định danh, Phân quyền RBAC & Session | [PERSISTENT_IDENTITY](docs/PERSISTENT_IDENTITY.md) |
| LangGraph Multi-Agent, Checkpoint & Interrupt | [LANGGRAPH](docs/LANGGRAPH.md) |
| Cơ sở dữ liệu PostgreSQL & pgvector | [POSTGRESQL](docs/POSTGRESQL.md) |
| RAG Trích dẫn tri thức & Provenance | [RAG_CHAT](docs/RAG_CHAT.md) |
| Ops Console & Giám sát vận hành | [ADMIN_CONSOLE](docs/ADMIN_CONSOLE.md) |
| Hạ tầng HTTPS, Caddy & Reverse Proxy | [PUBLIC_HTTPS](docs/PUBLIC_HTTPS.md) |
| Chiến lược kiểm thử tự động | [AUTOMATED_TEST_STRATEGY](docs/AUTOMATED_TEST_STRATEGY.md) |
| Thiết lập CI/CD & AWS SSM | [deploy/SETUP](deploy/SETUP.md) |

### 3. Kế hoạch & Lộ trình Khắc phục (Plans & Drift Remediation)

| Danh mục | Kế hoạch chi tiết |
| --- | --- |
| **Lộ trình Tổng thể** | [PLAN_ROADMAP_INDEX](docs/PLAN_ROADMAP_INDEX.md) · [PLAN_ADMIN_REMEDIATION_MASTER](docs/PLAN_ADMIN_REMEDIATION_MASTER.md) |
| **Phase R1 — Staff/Manager (implementation BLOCKED; W0 only)** | [Canonical design](docs/phase_role_aware_ops/README.md) · [Latest owner delta](docs/phase_role_aware_ops/W0_OWNER_DECISION_DELTA_2026-10-29.md) · [W0 register](docs/phase_role_aware_ops/W0_BASELINE_AND_DECISION_REGISTER_2026-10-27.md) · [Argon docs-review status and history](docs/phase_role_aware_ops/W0_REVIEW_RECONCILIATION_2026-10-28.md) · [Blocked readiness](docs/phase_role_aware_ops/IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md) |
| **Auto-seed remediation (vận hành)** | [Handoff, rà soát call sites và tiến độ kiểm chứng](docs/phase5/DEMO_ORDER_SEEDING_REMEDIATION_HANDOFF_2026-10-24.md) · [Biên bản cleanup đơn legacy](docs/04_OPERATIONS/ORDER_DATA_CLEANUP_2026-10-24.md) |
| **Khắc phục UI/UX** | [PLAN_FIX_UI_01](docs/PLAN_FIX_UI_01_TRUTHFUL_UX.md) (UX trung thực) · [PLAN_FIX_UI_02](docs/PLAN_FIX_UI_02_MANAGER_PERSISTENCE.md) (Bền vững hóa Manager) · [PLAN_FIX_UI_03](docs/PLAN_FIX_UI_03_OPSCONSOLE_INTEGRITY.md) (Chuẩn hóa Ops Telemetry) · [PLAN_FIX_UI_04](docs/PLAN_FIX_UI_04_CHAT_HISTORY_RESUME.md) (Khôi phục chat) |
| **Tính năng Đã Hoàn thành** | [PLAN_RBAC_GOOGLE_AUTH](docs/PLAN_RBAC_GOOGLE_AUTH.md) (Google SSO) · [PLAN_DATA_COLLECTION_FLYWHEEL](docs/PLAN_DATA_COLLECTION_FLYWHEEL.md) (Data Flywheel) · [PLAN_MCP_INTEGRATION](docs/PLAN_MCP_INTEGRATION.md) (FastMCP Server & Adapter) |
| **Mở rộng Đang Triển khai** | [PLAN_MULTIMODAL_ATTACHMENTS](docs/PLAN_MULTIMODAL_ATTACHMENTS.md) (Vision & File) · [PLAN_OMNICHANNEL_INTEGRATION](docs/PLAN_OMNICHANNEL_INTEGRATION.md) (Đa kênh) · [PLAN_ECOMMERCE_OPS_COPILOT](docs/PLAN_ECOMMERCE_OPS_COPILOT.md) (Co-pilot) |

## Phát triển và kiểm thử

Sửa code trên nhánh tính năng, bổ sung regression test, tạo PR, đợi CI xanh rồi merge. Workflow deployment trên main build/publish ECR, triển khai qua SSM và kiểm tra live smoke. Không copy source thủ công lên EC2.

CI giữ unit, HTTP, JavaScript, PostgreSQL/pgvector và Docker tests. Các module private/localhost còn trong source vì test và tương thích; chúng không còn là điều kiện để sử dụng web. Không xóa module hay database chỉ vì tên có chữ `api`, `local` hoặc `artifacts`.

**Chạy trên EC2 qua Session Manager, không chạy các lệnh sau trên PowerShell Windows:**

```bash
sudo python3 /opt/retailops/live-e2e.py --mode smoke
```

Full test có model call, dữ liệu test riêng và restart web, chỉ chạy trong phiên kiểm thử có chủ đích:

```bash
sudo python3 /opt/retailops/live-e2e.py --mode full
```

Các report lưu tại `/opt/retailops/e2e-reports/`. Full runner hiện kiểm tra HTTP qua Caddy, không phải Playwright/browser automation. Kết quả PASS không phải accuracy của model trên toàn bộ evaluation dataset.

## Nguồn model

Trong giao diện chọn Custom model (Colab/Ollama) hoặc API đã được cấu hình. EC2/web và thao tác trực tiếp không cần Colab; chat Custom cần model và endpoint đang hoạt động. Không tự chuyển provider khi một model lỗi. Không đưa token, API key hoặc URL chứa credential vào chat/Git.

[Notebook agent tự chứa](notebooks/colab_agent.ipynb) · [Bộ chọn model](docs/MODEL_SELECTOR.md) · [Hợp đồng agent](docs/AGENT_V04.md).

## Tài liệu lịch sử — không phải hướng dẫn khởi động hằng ngày

Các tài liệu được giữ làm bằng chứng quá trình phát triển, không dùng để quay lại quy trình copy token localhost:

- [Business API 0.2/0.3](docs/BUSINESS_API.md).
- [Hội thoại 0.3](docs/CONVERSATION_V03.md).
- [Baseline L4 đầu tiên](docs/BASELINE_L4_2026-09-06.md) và [baseline guide](BASELINE_GUIDE.md).
