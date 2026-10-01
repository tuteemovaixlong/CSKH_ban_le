# Kế Hoạch Kỹ Thuật: Tối Ưu Hiệu Năng & Bounded Concurrency (Runtime Efficiency & Concurrency)

> **Mục tiêu:** Giải quyết dứt điểm điểm nghẽn đơn luồng mô hình (*single global model lock bottleneck*) trong hệ thống RetailOps, bảo đảm khả năng phục vụ đồng thời cho nhiều khách hàng trên máy chủ WSGI Waitress (8 threads), kiểm soát áp lực ngược (*backpressure*), công bằng tài nguyên (*fairness*) và thu thập số liệu thực nghiệm khoa học cho Luận văn.
> **Snapshot đối chiếu:** Commit `c30ff1d` trên nhánh `main`.
> **Audit basis / Documentation baseline reviewed:** `c30ff1d` · **Application verified:** `c30ff1d`
> **Phân kỳ thực thi:** Tích hợp trực tiếp vào **Module 2.5 PR B** (Concurrency & Runtime Hardening), kế thừa nền tảng FIX 01–FIX 04 của Phase 1. GraphRAG v6.2 và Schema v5 (PR C) đã được hoãn sang Future ADR.

---

## 1. Điểm Nghẽn Concurrency: Snapshot Lịch Sử (`fd24e36`) & Hiện Trạng Baseline (`c30ff1d`/`d01f729`)

1. **Snapshot Lịch Sử (`fd24e36`)**:
   - Trước đây, `PersistentSessions` ([retailops/identity/persistent.py](../retailops/identity/persistent.py#L30)) và `PostgresSessions` ([retailops/identity/postgres.py](../retailops/identity/postgres.py#L17)) định nghĩa `self.agent_lock = threading.Lock()`.
   - Trong `Application.chat()`, `agent_lock.acquire(blocking=False)` bao trùm toàn bộ hàm `chat()`, khiến 1 model call đang chạy làm nghẽn toàn bộ khách hàng khác trên server Waitress 8 threads.
2. **Hiện Trạng Baseline Tại HEAD (`c30ff1d` / `d01f729`)**:
   - `Application.chat()` ([retailops/business/application.py:172](../retailops/business/application.py#L172)) đã chuyển `agent_lock` sang chỉ kiểm tra `if self.agent_lock.locked():` (fast rejection), và đồng bộ hóa phiên bằng `conv_lock` per-conversation cùng `InferenceGate`/`GatedGateway` cho model permits.
   - **Tồn dư cần dọn sạch trong PR B**: Xóa bỏ hoàn toàn biến `self.agent_lock` trong `application.py` và identity sessions; thay thế bằng cơ chế Full-Request Chat Admission Limiter kết hợp với `InferenceGate` (admission giới hạn tối đa 6 chat được nhận xử lý đồng thời trên Waitress 8 workers, giảm nguy cơ chat chiếm hết worker; không bảo đảm luôn có hai worker rảnh hoặc một pool riêng).

---

## 2. Kiến Trúc Điều Phối Đồng Thời 2 Giai Đoạn (Two-Stage Architecture)

### 2.1. STAGE 1: Bounded Concurrency Gate Tại Biên Model I/O (Giữ Nguyên Sync Waitress)

> [!IMPORTANT]
> **Nguyên Tắc Cốt Lõi: Khóa Slot Chỉ Dành Riêng Cho Actual Model Call**
> Tuyệt đối không giữ inference slot xuyên suốt cả turn của worker subagent. Slot chỉ được `acquire()` ngay trước khi gọi `gateway.chat()` / `gateway.chat_scoped()` và `release()` ngay trong khối `finally`. Các tác vụ đọc DB, truy vấn đồ thị Apache AGE, tìm kiếm vector RAG và thực thi tool hoàn toàn KHÔNG giữ inference slot.

```mermaid
flowchart TD
    Req["HTTP POST /api/chat"] --> Worker["Waitress Worker Thread (1/8)"]
    Worker --> Adm{"1. HTTP Chat Admission Limiter<br/>(Acquire non-blocking TRƯỚC session/DB preflight)<br/>In-flight chat < 6?"}
    Adm -- ">= 6 (Đầy slot)" --> Adm429["Trả ngay HTTP 429: server_busy<br/>(Header Retry-After: 5, 0 DB, 0 GPU)"]
    Adm -- "< 6 (Admitted)" --> SessionPre["2. Session Resolution & Request Read<br/>(Đọc body, sessions.resolve, nạp store)"]

    subgraph Preflight["Deterministic Preflight (Fast Path Read-Only, 0 Lock, 0 GPU)"]
        SessionPre --> Replay1{"3. Replay #1 Check?"}
        Replay1 -->|Hit| RetReplay["Return replay (<2ms)"]
        Replay1 -->|Miss| ConvLock["4. Acquire conv_lock (non-blocking)<br/>(Loser receives 429 model_busy immediately)"]
    end

    subgraph LockedPreflight["Under conv_lock: Replay #2, Snapshot Revalidation & Cache Commit"]
        ConvLock --> Replay2{"Replay #2 Check?"}
        Replay2 -->|Hit| RetReplay2["Return replay under lock"]
        Replay2 -->|Miss| RevalSnap["Reload & Revalidate Snapshot from DB"]
        RevalSnap --> CacheElig{"Cache Eligible?<br/>(No order/product context, static FAQ)"}
        CacheElig -->|Yes| SemCache{"SemanticCache.lookup?"}
        CacheElig -->|No (Bypass)| WfInit["Initialize Workflow Checkpoint"]
        SemCache -->|Hit| RetCache["finish_turn() under lock & return cache (<5ms)"]
        SemCache -->|Miss| WfInit
    end

    subgraph ExecutionLoop["Subagent Worker Execution Loop (InferenceGate Admission)"]
        WfInit --> Subagent["OrderAgent / DisputeAgent / PolicyAgent"]
        Subagent --> Gate1["InferenceGate.enter(timeout=10s)"]
        Gate1 --> ModelCall1["gateway.chat() #1 (Model I/O)"]
        ModelCall1 --> GateRel1["finally: InferenceGate.exit()"]

        GateRel1 --> ToolReq{"Tool Call Requested?"}
        ToolReq -->|No| Answer["Final Text Answer"]
        ToolReq -->|Yes| Tools["Execute Tools (ZERO GPU SLOT):<br/>get_order / check_inventory / PostgreSQL"]
        Tools --> Gate2["InferenceGate.enter(timeout=10s)"]
        Gate2 --> ModelCall2["gateway.chat() #2 (Model I/O)"]
        ModelCall2 --> GateRel2["finally: InferenceGate.exit()"]
        GateRel2 --> Answer
    end

    Answer --> Finish["store.finish_turn() under conv_lock"]
    Finish --> HTTP200["Release conv_lock, Release Chat Admission Token (finally) & HTTP 200"]
```

#### Các Yêu Cầu Kỹ Thuật Bắt Buộc Trong Stage 1:

1. **InferenceGate Độc Lập Tại Session Backend**:
   - Sử dụng `threading.BoundedSemaphore` riêng biệt cho từng Provider (`custom` vLLM vs `api` Cloud).
   - Hỗ trợ per-customer fairness: Mỗi `customer_id` tối đa 1 active model call, giải phóng an toàn khi gặp ngoại lệ.
2. **Chặn Trap Nuốt Lỗi Overload Trong `dispute_agent` (Bắt Buộc)**:
   - Trong `retailops/workflow/subagents/dispute_agent.py`, ngoại lệ overload (HTTP status 429) và lỗi hạ tầng (>= 500) bắt buộc phải re-raise ra ngoài để trả HTTP 429/503 cho client, tuyệt đối không nuốt thành phản hồi giả *"Dạ shop đã ghi nhận..."*.
3. **Cơ Chế Headroom Toàn Request & Backpressure Trên Sync Waitress**:
   - Waitress có 8 worker threads. `InferenceGate` ($K=1, Q=5$) chỉ kiểm soát biên gọi model I/O.
   - **Lỗ hổng headroom thực tế**: Nếu 8 request chat đồng thời cùng vào, các request đang thao tác DB, chuẩn bị context hoặc chạy tool ngoài gate vẫn chiếm trọn 8 worker threads của Waitress trước khi chạm tới `InferenceGate`, làm các request `/healthz` và `/api/session` bị starvation! Hơn nữa, nếu có nhiều provider riêng rẽ thì tổng gate giữa các provider cũng vượt quá số thread Waitress.
   - **Thiết kế Admission Toàn Request Chat (Full-Request Admission Gate)**:
     * Đặt Bounded Chat Admission Limiter tại tầng HTTP adapter (`PublicWeb.route()` / `PublicWeb.__call__`) **TRƯỚC** khi gọi `sessions.resolve()` và trước DB preflight.
     * Giới hạn tổng số request chat đang chiếm thread WSGI:
       $$\text{MAX\_INFLIGHT\_CHAT} \le \text{WAITRESS\_THREADS (8)} - \text{RESERVED\_THREADS (2)} = 6$$
     * Token request được acquire không chặn (`blocking=False`) ngay khi vừa nhận request tại adapter. Nếu active chat requests $\ge 6$, request bị từ chối ngay lập tức với HTTP 429 canonical error `server_busy` (kèm header `Retry-After: 5`) mà không động tới DB hay session store, không giữ worker thread chờ đợi.
     * Token được release an toàn trong khối `finally` của HTTP adapter (`PublicWeb`).
     * Áp dụng chung cho toàn bộ các provider: **Admission giới hạn tối đa 6 chat được nhận xử lý đồng thời trên Waitress 8 workers, giảm nguy cơ chat chiếm hết worker; không bảo đảm luôn có hai worker rảnh hoặc một pool riêng.**
     * Bên trong luồng chat (sau khi đã qua session resolution), mô hình đồng bộ 3 tầng (3-tier concurrency) áp dụng hợp đồng mã lỗi chuẩn xác:
       1. **Tier 1 (HTTP Chat Admission)**: Quá 6 in-flight $\to$ HTTP 429 canonical `server_busy` kèm `Retry-After: 5`.
       2. **Tier 2 (Per-Conversation Mutex - `conv_lock`)**: Đồng thời cùng session $\to$ HTTP 429 canonical `model_busy`.
       3. **Tier 3 (Model Permitted Gate - `InferenceGate` $K=1, Q=5$)**: Hàng đợi đầy (waiter thứ 6 / request thứ 7) $\to$ HTTP 429 canonical `model_busy` kèm `Retry-After: 5`; đã vào hàng đợi nhưng chờ quá 10s $\to$ HTTP 429 canonical `queue_timeout` (theo đúng `retailops/inference_gate.py:125-128`) kèm `Retry-After: 5`.
   - **Mục tiêu nghiệm thu Headroom có điều kiện (Conditional Acceptance SLO)**: Trong điều kiện load test có kiểm soát (cấu hình 1 tiến trình / Waitress 8 workers, 6 chat requests được giữ bằng test barrier/harness, giả lập độ trễ DB/tools/model chậm, tài nguyên dùng chung và DB không bị khóa chết), độ trễ `GET /healthz` và `GET /api/session` đo tại client đạt P99 $\le 50\text{ms}$. Phân biệt rõ tải bão hòa 6 chat được nhận xử lý với flood requests bị reject hàng loạt hoặc DB bị khóa; không suy diễn độ trễ endpoint từ phép trừ số học $8 - 6$.
4. **Chuẩn Hóa Fast-Path & Cache Serialization**:
   - `confirm_cancellation` là tuyến giao dịch HTTP độc lập (`POST /api/cancellation-proposals/{proposal_id}/confirm`), vốn dĩ không đi qua luồng chat inference.
   - Idempotency Replay #1 chạy ở fast-path ngoài lock.
   - Replay #2, tái thẩm định snapshot từ DB và Semantic Cache lookup/commit bắt buộc diễn ra **dưới phạm vi bảo vệ của `conv_lock`** (F02 FIX).
   - Tuyệt đối không ghi Semantic Cache nếu turn đã gọi bất kỳ tool nào (`len(tools) > 0` hoặc `tool_count > 0`, kể cả read tools như `get_current_time`).
5. **Xử Lý Race Condition Khi Invalidate Cache & Multi-Tenant ToolCache**:
   - `ToolCache` và epoch manager được sở hữu tập trung tại tầng phiên (`PersistentSessions` / `PostgresSessions`), chia sẻ cho các instance `Application` của cùng một tenant (thay vì mỗi `Application` tự tạo instance riêng).
   - Khóa cache phân tách tuyệt đối theo tenant: `(tenant_id, customer_id, tool_name, args_hash)`.
   - Gắn `cache_epoch` theo từng customer/tenant: Request chụp `current_epoch` trước khi gọi tool; khi Manager cập nhật đơn (`POST /api/manager/orders/update-status`) hoặc khách xác nhận hủy (`POST /api/cancellation-proposals/{id}/confirm`), DB commit thành công sẽ tăng `cache_epoch`. Các lệnh ghi tool cache in-flight có epoch lệch sẽ bị hủy bỏ (discard stale write nguyên tử bên trong `ToolCache._lock`), triệt tiêu race condition.
   - Phạm vi: Đóng gói an toàn trong tiến trình đơn máy chủ (in-process single-node WSGI).

---

### 2.2. STAGE 2: High-Scale Architecture (Chỉ Triển Khai Khi Benchmark Chứng Minh Stage 1 Chưa Đủ)

* Chỉ xem xét sau khi đã hoàn thành Khóa luận và có nhu cầu thương mại hóa:
  - Chuyển sang ASGI (Uvicorn / FastAPI / Starlette) với HTTP client bất đồng bộ (`httpx.AsyncClient`).
  - Triển khai Server-Sent Events (SSE) để stream token về trình duyệt nhằm giảm perceived latency (phải được chứng minh bằng benchmark thực tế, không claim trước `TTFT < 500ms`).
  - Mở rộng nhiều Web Replicas phía sau Load Balancer.

---

## 3. Quản Lý Kết Nối Cơ Sở Dữ Liệu & Pooling (Connection Pooling Contract)

1. **Nguyên Tắc Benchmark-First Cho Pooling**:
   - Hệ thống hiện tại sử dụng context manager `store.connection()` đóng/mở kết nối an toàn.
   - Chỉ bổ sung `psycopg-pool` vào `requirements.txt` nếu bài đo đạc ở Phase 4 chứng minh chi phí khởi tạo kết nối PostgreSQL > 5ms/turn.
2. **Quy Tắc Quản Lý Kết Nối Apache AGE**:
   - Tuyệt đối không duy trì kết nối AGE không được kiểm soát (*unmanaged connection*) tự do theo worker thread.
   - Nếu kích hoạt pool cho AGE:
     - Sử dụng bounded pool có configure/reset hook: Chạy `LOAD 'age'; SET LOCAL search_path = ag_catalog, pg_catalog;` khi checkout kết nối.
     - Cấu hình quyền read-only cho role `retailops`.
     - Chạy test kiểm tra rò rỉ phiên (session leakage test) trước khi hợp nhất.

---

## 4. Truthful Telemetry (Đo Đạc Chuẩn Xác Từng Thành Phần)

Bổ sung các trường telemetry vào cấu trúc trả về:

* **Per-Request Trace (Ghi vào `trace` của từng turn)**:
  - `queue_wait_ms`: Thời gian thực tế chờ slot trong InferenceGate (đo bằng `time.monotonic()`).
  - `provider_inference_ms`: Thời gian thực tế gọi mạng / suy luận model.
  - `graph_retrieval_ms`: Thời gian thực thi truy vấn Cypher trên Apache AGE.
  - `rag_retrieval_ms`: Thời gian tìm kiếm hybrid vector + lexical trên PostgreSQL.
  - `db_ms`: Tổng thời gian thực thi các truy vấn quan hệ.
  - `model_calls`: Số lượt gọi model thực tế trong turn ($N \ge 0$ lượt gọi; tích lũy theo số lần thực thi qua gateway trong turn, không quy ước cứng 1 hay 2 lượt; phân biệt rõ attempts và responses).
  - `prompt_tokens` & `generated_tokens`: Lấy từ telemetry thực tế của model provider; nếu provider không cung cấp thì gán `None` (Unknown) kèm `token_usage_available = False`, tuyệt đối không chia 3 và không tự gán 0.
  - `reported_cost_usd`: Lấy từ provider nếu có; nếu không thì để `None` (Unknown), không tự gán `$0.0`.
  - `e2e_latency_ms`: Tổng thời gian trọn vòng đời HTTP request đo tại server.
  - `in_flight_inferences`: Số lượng inference đang chạy đồng thời tại thời điểm hoàn thành turn.
  - **Duy trì đo đạc monotonic thời gian cache-hit**: Ghi nhận baseline hiện tại: `application.py:137` đã đo monotonic thời gian cache hit; bảo đảm duy trì đo đạc thực tế, không dùng số liệu hardcode.
  - **Hợp đồng Producer - Consumer (Ops Importer)**:
    * Tại `Application.chat()` (`application.py:273`): `provider_inference_ms` là tổng thời gian gọi model thực tế; khi không gọi model (cache hit), giá trị là `0.0`. Tuyệt đối không fallback gán bằng tổng độ trễ `latency_ms`.
    * Tại Ops Console importer (`opsconsole/evaluation.py:215`): Sửa logic `number(val) or latency_ms` để bảo toàn giá trị `0.0` của cache hit (không biến thành `latency_ms`), và giữ nguyên `null`/Unknown khi dữ liệu chưa đo.
* **Process / Ops Metrics (Chỉ số tổng hợp cấp tiến trình)**:
  - `overload_429_count`: Đếm tổng số lượt request bị từ chối do quá tải (vì request bị 429 không có completed turn để lưu vào DB).

---

## 5. Phương Án Benchmark Đo Đạc Runtime & Concurrency

Quy trình kiểm thử tải đồng thời phục vụ Chương 4 Khóa luận (triển khai độc lập trong Phase 4, không làm thay đổi hay ô nhiễm bộ benchmark chức năng):

* **Tải Đo Đạc**: `concurrency = 1, 2, 4, 8, 16` luồng đồng thời.
  - *Ghi chú khoa học*: Khi `concurrency > 8` (vượt quá 8 worker threads của Waitress), bài test đo lường cả độ trễ xếp hàng HTTP của WSGI server.
* **Bộ Chỉ Số Thu Thập**:
  1. **Throughput & Latency**: RPS thành công, E2E Latency (p50, p95, p99).
  2. **Thời Gian Xếp Hàng & Xử Lý**: Queue wait (`queue_wait_ms` p50, p95), Provider inference time (`provider_inference_ms` p50, p95).
  3. **Tỷ Lệ Thành Công & Áp Lực Ngược**: Tỷ lệ hoàn thành nghiệp vụ (Success rate %), Tỷ lệ lỗi 429 quá tải (Overload 429 rate %).
  4. **Hiệu Quả Tài Nguyên & Chi Phí**: `model_calls/request`, `prompt_tokens/request`, `generated_tokens/request`, `cost/1000 successful requests`.
  5. **Tính Công Bằng Giữa Các Khách Hàng**:
     - Sử dụng chỉ số **Jain's Fairness Index** để đánh giá tính công bằng trong phân bổ tài nguyên suy luận.
     - Sử dụng độ phân tán thời gian chờ (**wait-time dispersion / standard deviation**) để đo độ lệch độ trễ giữa các khách hàng.
  6. **Độ Tin Cậy & Cô Lập**: Tool Accuracy %, Citation Validity %, và kiểm tra cô lập dữ liệu tuyệt đối giữa các khách hàng (zero cross-customer leakage).
  7. **Tiêu Thụ Tài Nguyên Hệ Thống**: CPU %, RAM sử dụng, và VRAM peak (khi chạy trên GPU).

---

## 6. Bảo Vệ Bộ Benchmark 250 Ca Đã Đóng Băng (Frozen Baseline Protection)

> [!IMPORTANT]
> **Nguyên Tắc Bất Biến Về Dữ Liệu Thực Nghiệm Khoa Học Cho Luận Văn:**
> 1. **Frozen Baseline**: Toàn bộ **250 kịch bản Master Benchmark** (`evals/scenarios/master_250_v1.jsonl` và `evals/scenarios/benchmark_250.jsonl` với SHA-256 đã ghim chặt: `36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411`) là bộ dữ liệu đánh giá **ĐÃ ĐÓNG BĂNG**.
> 2. **Không Thay Đổi Benchmark**: Tuyệt đối KHÔNG thay đổi câu hỏi, không nới lỏng tiêu chí chấm điểm, và không lọc bỏ các ca khó để "làm đẹp" số liệu độ chính xác (Router Accuracy / Resolution Rate).
> 3. **Cơ Sở Đo Lường Đối Chứng Module 6**: Mọi thực nghiệm so sánh khoa học giữa mô hình self-hosted Gemma-4-12B và DeepSeek Cloud API trong Chương 4 Luận văn tốt nghiệp bắt buộc phải chạy trên cùng một bộ 250 kịch bản cố định này để bảo đảm tính khách quan, có thể tái lập (reproducibility) và trung thực học thuật.
