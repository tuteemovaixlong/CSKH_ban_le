# Đánh giá hệ thống RAG, Workflow và LLM — RetailOps

Ngày đánh giá: **2026-10-02** · Code snapshot: **`376322f`**.

**Kết luận: hệ thống đang ở mức prototype tích hợp có kiểm soát, chưa đủ điều kiện hoặc bằng chứng để xác nhận pilot thực tế/production-ready.** Kiến trúc nền phù hợp CSKH bán lẻ; khoảng trống chính nằm ở tính đúng đắn của runtime, bắt buộc dùng bằng chứng và đánh giá chất lượng model thật.

Tài liệu này là **đánh giá và kế hoạch đề xuất**, không phải xác nhận đã triển khai. Phạm vi: đọc code, tests, CI, báo cáo lưu trong repository và các plan liên quan. Không gọi model/API, khởi tạo DB, chạy load test hay xác nhận deployment đang hoạt động. Không chỉnh sửa mã nguồn hoặc tài liệu có sẵn.

## 1. Trả lời trực tiếp

| Câu hỏi | Đánh giá |
|---|---|
| Có phải hệ thống RAG/workflow thật không? | **Có.** PostgreSQL/pgvector retrieval được nối vào tool loop; LangGraph, checkpoint, scoped tools và backend nghiệp vụ đã có code. |
| Phần LLM đã đạt chuẩn chưa? | **Đạt nền tảng kỹ thuật cho prototype; chưa chứng minh chất lượng đủ cho pilot thật.** Không có một “chuẩn LLM” chung chỉ cần có RAG hoặc multi-agent là đạt. |
| Hiện tại ở mức nào? | **M1 — Prototype có kiểm soát**, theo thang nội bộ ở mục 2. Một số thành phần đã có thiết kế tốt hơn mức này, nhưng toàn hệ thống bị giới hạn bởi các chốt an toàn và chất lượng chưa hoàn tất. |
| Mức cần đạt gần nhất? | **M2 — Pilot có kiểm chứng:** PR A/B chạy đúng, policy claims có evidence, retry an toàn, telemetry thật và đánh giá model thật có nhãn. |
| Thiếu gì nhất? | Runtime Module 2.5; gate bắt buộc retrieval/abstention; thống nhất worker/provider/checkpoint; bộ chấm outcome và groundedness; quản trị nguồn tri thức thật. |
| Có cần GraphRAG hoặc fine-tune ngay? | **Chưa cần.** Chỉ nâng cấp khi evaluation cho thấy hạn chế cụ thể và phương án mới thắng baseline. |

**“Plan Module 2.5 READY” nghĩa là đặc tả sẵn sàng để thực thi.** Các AC-01…AC-13 trong [plan hardening](PLAN_MODULE_2_5_HARDENING_VERIFICATION.md) vẫn ghi `PENDING TEST`; code hiện tại còn các lỗi tương ứng. Không được chuyển ý nghĩa READY của tài liệu thành PASS của runtime.

## 2. Thang trưởng thành dùng cho đánh giá

Đây là rubric riêng cho project, **không phải chứng nhận ngành**, và không trùng với cấp minh chứng L1–L4 của release manifest.

| Mức | Tiêu chí | Hiện trạng |
|---|---|---|
| M0 — Demo | Trả lời được một số tình huống, chất lượng chủ yếu quan sát thủ công. | Hệ thống đã vượt mức này về kiến trúc. |
| **M1 — Prototype có kiểm soát** | Tool schemas, ownership/confirmation, bounded loops, checkpoint, tests và citation provenance. | **Mức hiện tại của toàn hệ thống.** |
| M2 — Pilot có kiểm chứng | Chốt fail-closed chạy đúng; bộ đánh giá có nhãn; model thật và failure/load tests trên topology mục tiêu; mở giới hạn với giám sát/handoff. | Mục tiêu gần; còn các blocker ở mục 5–8. |
| M3 — Production trong miền giới hạn | Thêm tri thức được phê duyệt/có hiệu lực; retention/privacy; SLO; rollback/recovery; chất lượng được theo dõi và hành động nghiệp vụ có acknowledgement bền vững. | Chưa đủ bằng chứng để xác nhận. |
| M4 — Vận hành cải tiến liên tục | Model/prompt/KB thay đổi qua quality gates, canary, feedback được duyệt và tối ưu có đối chứng. | Hướng phát triển sau pilot. |

Không gán tỷ lệ kiểu “đã hoàn thành 80%”: số file, số agent, số test hoặc kích thước model không đo được mức đúng của câu trả lời.

## 3. Kiến trúc thực tế và những phần đã tốt

### 3.1. Luồng thực tế

`PublicWeb → session/binding → Application.chat → semantic lookup → conv_lock khi cache miss → LangGraph supervisor → một worker → model/tool loop → citation check → finish_turn → response`.

Luồng trên mô tả **code hiện tại**, bao gồm điểm lookup/cache-hit trước `conv_lock` cần sửa. Kiến trúc đích phải đưa replay/revalidation/cache path vào đúng ranh giới khóa theo PR A.

Supervisor hiện là router chủ yếu theo luật/từ khóa. Các worker order/policy/dispute/witty đi tới `END` sau xử lý; không có vòng tự cộng tác giữa nhiều agent. Đây là lựa chọn hợp lý cho miền CSKH có quy trình rõ, không phải dấu hiệu kiến trúc yếu. Bằng chứng: [graph.py](../retailops/workflow/graph.py), dòng 25–84.

RAG runtime: tài liệu → chunk theo đoạn → feature-hash vector 384 chiều → PostgreSQL hybrid search → excerpts giới hạn → worker/model → citation provenance. **Đây là lexical + feature-hash baseline**, không phải neural semantic retrieval hoặc GraphRAG đã triển khai.

### 3.2. Năng lực đã hiện diện trong code

| Thành phần | Giá trị thực tế | Bằng chứng |
|---|---|---|
| Backend sở hữu nghiệp vụ | Identity từ session; kiểm tra quyền/sở hữu và confirmation tách khỏi lời nói của model. | [routes.py](../retailops/http/routes.py), [approval.py](../retailops/workflow/approval.py), [store.py](../retailops/business/store.py):684–704. |
| Tool contract | Schema tham số, validation transcript và allowlist; worker order/policy hạn chế phạm vi ở transport và execution. | [agent_protocol.py](../agent_protocol.py):90–128, 345–356; [read_worker.py](../retailops/workflow/subagents/read_worker.py):108, 218–224. |
| Giới hạn xử lý | Order/policy dùng tối đa 4 model calls, 8 tool calls; knowledge có budget riêng. | [agent_protocol.py](../agent_protocol.py):7–8; [read_worker.py](../retailops/workflow/subagents/read_worker.py):158–194. |
| Persistence/replay | DB checkpoint, lease/fencing, tenant/customer scope; commit kiểm tra revision hội thoại/version đơn. | [checkpoints.py](../retailops/workflow/checkpoints.py); [store.py](../retailops/business/store.py):684–704. |
| RAG isolation/provenance | Tenant schema do server chọn; sources từ excerpt thật có hash; không cho model tự tạo mảng nguồn. | [postgres.py](../retailops/storage/postgres.py):31–39, 61–72; [tool.py](../retailops/knowledge/tool.py):69–94; [citations.py](../retailops/knowledge/citations.py):15–28. |
| Fallback dựa trên dữ kiện | Order/policy có renderer trả dữ kiện đã lấy nếu model gặp lỗi; tránh tự chuyển provider. | [read_worker.py](../retailops/workflow/subagents/read_worker.py):163–177; [policy_agent.py](../retailops/workflow/subagents/policy_agent.py):13–48; [application.py](../retailops/business/application.py):308–311. |
| Concurrency nền | Có mutex từng hội thoại và FIFO inference gate, queue timeout và giải phóng slot. | [inference_gate.py](../retailops/inference_gate.py). |
| Kiểm thử nền | Unit/integration cho tools, citations, checkpoints, ownership; CI có PostgreSQL/pgvector; có live E2E harness. | [ci.yml](../.github/workflows/ci.yml); [test_rag_chat.py](../tests/test_rag_chat.py); [live-e2e.py](../deploy/live-e2e.py). |

Các điểm trên là **code đã đọc**, không đồng nghĩa mọi nhánh chạy đúng hoặc CI hiện tại đã PASS.

## 4. RAG hiện tại đáp ứng được gì, còn thiếu gì?

| Lớp RAG | Hiện trạng | Mức phù hợp pilot |
|---|---|---|
| Embedding | `feature-hash-v1`, 384D, deterministic; có unigram/bigram/character features. | Baseline được đánh giá trên tiếng Việt; chỉ thay neural embedding nếu chất lượng retrieval chưa đạt. |
| Retrieval | Score cố định 0.75 vector + 0.25 lexical; cutoff 0.15 và literal token overlap. | Hiệu chuẩn bằng relevance labels; đo paraphrase, dấu/không dấu, SKU, nhiều intent và no-answer. Score không được diễn giải là xác suất đúng. |
| Chunking | Theo đoạn, target 900 ký tự/overlap 140; excerpt tối đa 1.100 ký tự. | Không cắt mất điều kiện/ngoại lệ chính sách; parser phù hợp với định dạng tài liệu thật. Token/structure-aware chunking tùy nhu cầu. |
| Context budget | Tối đa 2 searches, 3 excerpts/search, 2.800 serialized chars/reply, 3.600 chars/turn. | Đo recall sau truncate và mức đủ bằng chứng; có đường clarify/handoff cho câu vượt budget. |
| Grounding | Citation ID phải thuộc evidence của turn. | Policy fact phải lấy bằng chứng hoặc abstain; đánh giá claim được nguồn hỗ trợ. |
| Freshness | Documents có checksum/active/updated_at; ToolCache có TTL. | Nguồn được phê duyệt/có applicability; sửa/xóa nguồn làm lookup mới dùng đúng revision. |
| Scale | Có GIN/HNSW indexes; query rank score tổng hợp trên active chunks. | EXPLAIN và load test trước khi tuyên bố index tăng tốc; candidate generation/fusion chỉ tối ưu khi cần. |

Bằng chứng: [embedding.py](../retailops/knowledge/embedding.py):1–43; [repository.py](../retailops/knowledge/repository.py):43–96; [chunking.py](../retailops/knowledge/chunking.py):63–83; [tool.py](../retailops/knowledge/tool.py):11–89.

**Hai khái niệm cần tách:** citation provenance chứng minh excerpt đã được lấy; groundedness chứng minh phát biểu được excerpt hỗ trợ. Citation đúng ID vẫn có thể đi kèm diễn giải sai. Có pgvector cũng không tự chứng minh hiểu ngữ nghĩa tiếng Việt tốt.

## 5. Các phát hiện cần xử lý

P1: chặn chuyển sang pilot thật hoặc làm mất giá trị bằng chứng chất lượng. P2: cần hoàn thiện trước mở phạm vi tương ứng. Mã `LLM-xx` thuộc tài liệu này; không thay thế mã F/R của plan cũ.

### LLM-01 — P1: Hardening Module 2.5 chưa hiện diện đầy đủ trong runtime

- **Cache:** lookup tại `application.py:130`, cache-hit commit tại `:166`, lấy `conv_lock` tại `:178`. Store guard `:296–300` chưa kiểm đủ FAQ/history/tools/RAG/provenance. Có thể trả đáp án từ ngữ cảnh hoặc nguồn cũ; DB revision checks không thay thế guard chọn đáp án.
- **ToolCache:** tạo riêng từng Application (`:39`); khóa `customer:tool:args` tại `cache.py:190–192`, chưa có shared ownership/epoch/CAS như F13. Đây là khoảng trống hợp đồng khi chia sẻ cache, **không phải bằng chứng đã rò dữ liệu chéo tenant**.
- **Runtime:** Waitress 8 threads; HTTP adapter chưa có admission trước session/body/DB; queue mặc định vẫn 8 thay vì target 5. Chưa có bằng chứng headroom/load đạt mục tiêu.
- **Retention:** `store.py:702–704` vẫn xóa lượt vượt cửa sổ 6. Giữ prompt ngắn và giữ audit history là hai hợp đồng khác nhau.
- **Dispute:** còn tự mặc định size L/màu “Tiêu chuẩn”, gộp unknown thành hết hàng và phản hồi thành công giả khi exception.

**Hướng xử lý:** thực thi PR A rồi PR B; không coi tài liệu READY là thay thế code/tests. Kiểm cả cache-hit, replay, manager mutation và in-flight stale write; giữ số worker/queue/status theo canonical plan. Chỉ giới hạn 6 chat được nhận không bảo đảm luôn có 2 worker rảnh dưới mọi loại tải.

**Bằng chứng:** [application.py](../retailops/business/application.py):129–178, 296–300; [cache.py](../retailops/business/cache.py):182–237; [inference_gate.py](../retailops/inference_gate.py):26–31; [public.py](../retailops/http/public.py):111–131; [bootstrap.py](../retailops/bootstrap.py):51–53; [dispute_agent.py](../retailops/workflow/subagents/dispute_agent.py):196–204, 241–252.

### LLM-02 — P1: Không bắt buộc retrieval trước khi trả policy fact

Policy prompt yêu cầu search, nhưng `read_worker.py:180–189` chấp nhận final prose ngay khi model không gọi tool. `cited_sources(answer, [])` trả `[]`; Application chấp nhận. Model bỏ qua prompt có thể trả một quy định cửa hàng không có evidence. Retrieval rỗng cũng chưa có gate backend cấm model đoán chính sách.

**Hướng xử lý:** hợp đồng theo intent: policy claim cần evidence phù hợp hoặc câu abstain/clarify/handoff. Không dùng việc model tự nói “đã xác minh” làm bằng chứng. Citation validity và semantic support phải có tiêu chí riêng. Câu hỏi thông thường không cần chính sách không nên bị ép retrieval.

**Test nghiệm thu:** zero-tool policy answer; empty/irrelevant evidence; fabricated citation; nguồn có thật nhưng không hỗ trợ claim; câu hỏi thiếu điều kiện; mixed policy + owned-order fact.

**Bằng chứng:** [policy_agent.py](../retailops/workflow/subagents/policy_agent.py):5–9; [read_worker.py](../retailops/workflow/subagents/read_worker.py):178–190; [citations.py](../retailops/knowledge/citations.py):21–28; [application.py](../retailops/business/application.py):280–288.

### LLM-03 — P1: Sửa Application boundary chưa đủ để bảo toàn lỗi qua toàn workflow

`Application.execute()` đang chuyển mọi ApiError thành dict. Dispute broad catch có thể trả “shop đã ghi nhận”. PR A đã nhận diện phần này, nhưng `read_worker.py:230–233` còn bắt ApiError và bỏ HTTP status. Nếu chỉ re-raise ở Application, worker vẫn có thể chặn lại tool 429; `model_busy`/`queue_timeout` không nằm trong tập `UNAVAILABLE`.

Provider HTTP 429 đi qua `AgentError`; Application hiện map mọi AgentError thành 503. Gate 429 ở đường gọi model của order/policy có thể đi ra nguyên vẹn; không nên kết luận mọi 429 đều bị nuốt. Fallback từ dữ kiện đã xác minh là hợp lệ khi được ghi rõ degraded; khác với báo side effect thành công khi chưa có acknowledgement.

**Hướng xử lý/test:** quyết định và kiểm hợp đồng riêng cho HTTP admission 429 `server_busy`, conv_lock/gate-full 429 `model_busy`, queue timeout 429 `queue_timeout`, tool 429, DB 503, upstream provider 429, partial-data fallback. Status, error code, Retry-After và outcome phải nhất quán qua từng boundary.

**Bằng chứng:** [application.py](../retailops/business/application.py):235–242, 302–307; [read_worker.py](../retailops/workflow/subagents/read_worker.py):15–17, 230–246; [dispute_agent.py](../retailops/workflow/subagents/dispute_agent.py):241–252; [retailops_providers.py](../retailops_providers.py):262–267.

### LLM-04 — P2: Citation lỗi sau checkpoint final có thể khiến retry lặp đáp án lỗi

Multi-agent worker đánh dấu complete trước khi graph checkpoint; Application mới kiểm citation sau graph. Khi citation invalid/missing, response bị từ chối nhưng checkpoint final đã tồn tại. Retry cùng request có thể lấy nguyên `checkpoint.values`, trả cùng đáp án rồi fail lại. Single-agent kiểm citation trước final checkpoint nên không có cùng thứ tự này.

**Hướng xử lý:** final validation trước checkpoint complete, hoặc cơ chế retry/invalidate final được thiết kế rõ. Resume phải đối chiếu protocol/model/prompt identity; multi-agent hiện chưa có guard tương đương single-agent. Crash giữa model/tool loop trong một worker cũng có thể replay cả loop; không tuyên bố exactly-once cho model/tools.

**Test:** invalid/missing citation rồi retry cùng key; crash sau read tool; đổi model digest/protocol/prompt trong lúc resume; stale conversation revision; side effect không bị nhân đôi.

**Bằng chứng:** [read_worker.py](../retailops/workflow/subagents/read_worker.py):310–315; [graph.py](../retailops/workflow/graph.py):97–99; [application.py](../retailops/business/application.py):280–295; [agent.py](../retailops/workflow/agent.py):73–79, 119–122.

### LLM-05 — P2: Base prompt không đồng nhất giữa provider

Ollama `build_request()` lấy worker system message làm system thay master prompt; API adapter ghép master + worker. Vì vậy cùng câu hỏi/tool scope không chắc có cùng base policy về untrusted context và dữ liệu. Không có live evidence để kết luận model nào tuân thủ tốt hơn.

**Hướng xử lý/test:** base policy dùng chung có version, worker supplement và tool scope rõ; kiểm parity payloads cho các provider, bao gồm prompt injection trong retrieved passages. Giữ business permissions ở backend.

**Bằng chứng:** [agent_protocol.py](../agent_protocol.py):365–370; [retailops_providers.py](../retailops_providers.py):219–229; [read_worker.py](../retailops/workflow/subagents/read_worker.py):20–26.

### LLM-06 — P2: Deadline và budget chưa thống nhất mọi worker

`run_multiagent(timeout=110)` nhận nhưng không dùng deadline toàn turn. Workers có timeout riêng; dispute xử lý các tool calls bằng runtime riêng, chưa kiểm `MAX_TOOL_CALLS`/`validate_tool` tương đương read worker. Budget từng worker không tự giới hạn tổng thời gian queue + model + tool + storage.

**Hướng xử lý/test:** deadline monotonic xuyên turn; check phần thời gian còn lại trước I/O, timeout ở adapter/tool; dùng contract chung cho mọi worker. Cancellation phải bảo toàn trạng thái và giải phóng slot. Test nhiều model rounds, batch tool lớn, tool/DB chậm, timeout giữa checkpoint và commit.

**Bằng chứng:** [graph.py](../retailops/workflow/graph.py):28–45, 87–99; [read_worker.py](../retailops/workflow/subagents/read_worker.py):155–194; [dispute_agent.py](../retailops/workflow/subagents/dispute_agent.py):56–80.

### LLM-07 — P2: Human handoff và guardrails cần trạng thái thực tế

Supervisor có thể nói đã gửi cảnh báo/kết nối, rồi graph gọi `request_human_support` ngoài vòng trace/checkpoint và nuốt exception. Counter OOD bị reset mỗi request; cutoff hội thoại không tích lũy. Topic filter chạy trước rage escalation; từ “khởi kiện” có thể bị phân loại tư vấn luật thay vì khiếu nại cần handoff.

**Hướng xử lý/test:** chỉ báo đã tạo yêu cầu sau durable acknowledgement; idempotency và trace cho handoff; lưu đúng state xuyên turn; phân biệt retail complaint với yêu cầu tư vấn pháp luật. Test handoff failure/retry, hai lượt OOD liên tiếp, lời đe dọa khiếu nại trong ngữ cảnh đơn hàng.

**Bằng chứng:** [graph.py](../retailops/workflow/graph.py):142, 154–160; [supervisor.py](../retailops/workflow/supervisor.py):90–136; [topic_filter.py](../retailops/guardrails/topic_filter.py):20; [witty_agent.py](../retailops/workflow/subagents/witty_agent.py):81.

### LLM-08 — P2: Vòng đời tri thức và freshness chưa đủ cho chính sách thật

Ingest chỉ thay tài liệu được đưa vào; nguồn bị xóa khỏi thư mục không tự bị retire. Replace xóa chunks cũ. Metadata hiện chưa enforce approval, effective window, applicability hoặc ACL từng tài liệu. Tenant isolation đã có, nhưng không thay thế quyền đọc tài liệu nội bộ trong cùng tenant khi xuất hiện nhu cầu đó.

`search_knowledge` nằm trong ToolCache TTL 180s, khóa chưa chứa KB/index revision. Evidence đúng hash vẫn có thể thuộc chính sách cũ. Epoch/CAS F13 dành cho ToolCache và mutation đồng bộ; chưa tự giải quyết vòng đời cập nhật KB.

**Hướng xử lý/test:** owner nguồn, trạng thái duyệt, điều kiện áp dụng, revision/effective dates; retire nguồn; KB revision invalidation hoặc bypass cache policy search theo hợp đồng. Phân biệt replay lịch sử được giữ excerpt cũ với lookup mới phải dùng nguồn hiện hành. Chỉ thêm ACL khi có lớp tài liệu cần hạn chế. Không coi mọi chính sách “7 ngày/15 ngày” là mâu thuẫn nếu chưa kiểm phạm vi áp dụng.

**Bằng chứng:** [repository.py](../retailops/knowledge/repository.py):47–65, 80; [pg_schema.py](../retailops/storage/pg_schema.py):60–73; [cache.py](../retailops/business/cache.py):182–192; [application.py](../retailops/business/application.py):228–234.

### LLM-09 — P2: Provider reasoning có đường lưu DB và hiển thị UI

Khi provider trả `reasoning`/`reasoning_content`, adapter trả trường đó; read worker sao chép vào `trace.reasoning` và `steps[].thought`. Application trả nguyên trace; `finish_turn` lưu result/trace; UI hiển thị thought/raw reasoning. Single-agent cũng copy reasoning. Đây là đường dữ liệu **có điều kiện theo provider**, không khẳng định mọi response chứa reasoning.

Code comment “never SQLite/trace/UI” hiện không đúng với toàn đường dữ liệu. Trace đang trộn mô tả hoạt động do server tạo và reasoning của provider.

**Hướng xử lý/test:** public trace theo allowlist gồm tool/action/status/timing/source và tóm tắt vận hành; không dùng raw reasoning làm chứng cứ “đã xác minh”. Có hợp đồng riêng về quyền đọc/retention nếu lưu dữ liệu nội bộ; kiểm response, error trace, checkpoint, DB log, transcript và resume UI. Roadmap CoT nên được diễn giải lại thành action/evidence trace hữu ích cho người dùng.

**Bằng chứng:** [retailops_providers.py](../retailops_providers.py):462–479; [read_worker.py](../retailops/workflow/subagents/read_worker.py):114–120, 186, 275; [agent.py](../retailops/workflow/agent.py):51–52; [store.py](../retailops/business/store.py):695–705; [web/app.js](../web/app.js):883–886, 920–924, 1013.

### LLM-10 — P1: Telemetry và evaluation chưa đủ để xác nhận chất lượng

Runtime lấy graph/turn latency làm provider inference time và mặc định retrieval/DB time bằng 0. Importer đổi `0.0` hợp lệ thành tổng latency qua `number(val) or latency_ms`; còn suy actual mode từ expected mode khi `passed=True`, suy 1 model call từ HTTP 200 và missing queue time thành 0.

**Hướng xử lý:** đo actual calls/attempts/results, mode/worker và các duration riêng; thiếu dữ liệu là unknown/null. 0 chỉ đúng khi biết không có hoạt động, chẳng hạn model time của cache-hit. Không suy routing/model count từ nhãn PASS. Thiếu bộ chấm semantic/outcome được trình bày ở mục 6.

**Bằng chứng:** [application.py](../retailops/business/application.py):272–276; [graph.py](../retailops/workflow/graph.py):124–128; [evaluation.py](../opsconsole/evaluation.py):171–172, 203–215.

## 6. Bằng chứng chất lượng hiện có đáng tin đến mức nào?

### 6.1. Không dùng 100% routing để kết luận 100% LLM accuracy

[Runner offline](../scripts/run_benchmark_eval.py):90–116 chỉ gọi `run_supervisor`, chấm routing và một số safety flags. Không chạy worker/model/retrieval hoặc kiểm hậu trạng thái nghiệp vụ. Báo cáo [250/250](../evals/reports/benchmark_report_20260920_150526.md):12 là kết quả router theo bộ đó; latency của router không phải chat latency.

[Runner live HTTP](../scripts/run_live_benchmark_http.py):206–237 chấm PASS khi HTTP 200 và không gọi forbidden tools. Có tính `extra_tools` nhưng không bắt buộc expected tools/outcome; thu sources nhưng không chấm relevance/claim support. Một lời đáp chung chung vẫn có thể PASS. Latency được chụp trước `resp.read()` tại :68–69; retry chỉ giữ thời gian lần cuối, chưa phải toàn bộ thời gian người dùng chờ. Cần tách first-attempt success, eventual success và total duration; không gọi số đo này là TTFT khi chưa đo streaming.

### 6.2. Artifact live lưu sẵn không đại diện baseline hiện tại

Đọc [live_benchmark_report_latest.json](../evals/reports/live_benchmark_report_latest.json) trong bộ nhớ cho thấy:

- Timestamp **20260918_042301**; metadata ghi custom Qwen 2.5 4B; **227/240 PASS = 94,6%**.
- 240 IDs không giao với 250 IDs của frozen master hiện tại; split lịch sử 120/120, frozen hiện tại 150/100.
- 227 response PASS cùng mở đầu bằng “Chào bạn, RetailOps AI đã tiếp nhận yêu cầu…”. Có **37 cases có sources**, không có case-level trace trong artifact này.
- Chưa có code commit, model digest, dataset-content hash và grader version để gắn run với hệ thống đang đọc.

Các đặc điểm đó **không chứng minh artifact bị giả**; chúng chứng minh chưa đủ căn cứ dùng 94,6% làm chất lượng RAG/LLM tại snapshot hiện tại. Cũng chưa xác nhận model nào đang thật sự được serve hôm nay: tên/default trong code hoặc plan không thay thế runtime identity.

### 6.3. Tests hiện tại có giá trị nhưng không thay live quality evaluation

RAG/multi-agent tests dùng scripted/mock gateway; PostgreSQL tests phụ thuộc DSN. CI có provision pgvector, nhưng lượt này không lấy kết quả run CI. Application còn tự chọn single-agent cho một số mock class names tại `application.py:40–49`; test workflow PASS không mặc nhiên chứng minh production multi-agent có cùng hành vi replay/failure.

Có live E2E harness kiểm tools/sources/confirmation/restart, là canary hữu ích. Cần chạy và lưu minh chứng trên đúng commit/provider để bổ sung, không coi canary là đánh giá đầy đủ tất cả câu hỏi.

[Ops summary](../opsconsole/evaluation.py):78–83 chủ động để recall/groundedness/task_success là null — điều này trung thực. Metric functions đã có, nhưng cần relevance judgments và outcome labels thật mới tính được chỉ số có ý nghĩa.

## 7. Đối chiếu các plan: điểm đúng và khoảng trống

| Tài liệu | Nhận xét khi đối chiếu code |
|---|---|
| [PR A](PLAN_PR_A_CONTEXT_CACHE_DISPUTE.md), [Module 2.5](PLAN_MODULE_2_5_HARDENING_VERIFICATION.md) | Nhận diện đúng nhóm correctness/cache/dispute. Implementation còn pending; bổ sung kiểm F03 tại read-worker boundary và citation final/retry, không chỉ Application/dispute. |
| [Runtime](PLAN_RUNTIME_EFFICIENCY_CONCURRENCY.md), [Sprint](PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md) | Hướng admission/conv_lock/inference slot riêng, epoch/CAS ToolCache và telemetry là hợp lý. Bổ sung deadline toàn turn, KB revision và importer actual mode/count. Epoch/CAS không tự động là tính năng hiện có của SemanticCache. |
| [RBAC/OAuth](PLAN_RBAC_GOOGLE_AUTH.md) | Session/permissions đã có nền; SEC-01 browser binding/atomic consume còn pending. Code OAuth TTL hiện 900s, đặc tả mới 600s. Đây là deployment prerequisite liên quan, không phải thước đo retrieval quality. |
| [RAG_CHAT](RAG_CHAT.md) | Mô tả feature hashing và provenance limitations trung thực. Câu “citation fail trước final checkpoint” tại dòng 51–55 đúng với single-agent nhưng chưa đúng đường multi-agent hiện tại; xem LLM-04. |
| [Current status](CURRENT_PROJECT_STATUS.md) / [Roadmap](PLAN_ROADMAP_INDEX.md) | Status dòng 23, 104 còn F10/migration v5/PR C trong sprint; roadmap đã hoãn PR C. Cần dùng scope A → B của canonical hardening khi triển khai. |
| [GraphRAG](PLAN_GRAPHRAG_AGE.md) | Là thiết kế/nâng cấp nghiên cứu, chưa phải RAG runtime đã triển khai. Roadmap giới hạn nghiên cứu offline; một số plan vẫn nhắc AGE như đường runtime. Không đưa AGE thành prerequisite pilot. |
| [Model selection](PLAN_MODEL_SELECTION_STRATEGY.md) | Có hướng so sánh cùng dataset/provider tường minh. Sơ đồ general cache còn đơn giản hơn guard static FAQ/history trong PR A; phải ưu tiên canonical guard. Tên model trong plan chưa xác nhận deployment hiện tại. |
| [MCP](PLAN_MCP_INTEGRATION.md) | Ghi rõ standalone implemented/production wiring pending; production gọi BoundTools trực tiếp. Có MCP server không đồng nghĩa chat chạy qua MCP hoặc chất lượng tool reasoning tốt. |
| [Evaluation](PLAN_DEEPSEEK_EVAL_FRAMEWORK.md), [fine-tuning](PLAN_FINE_TUNING_SERVING.md), [distillation](PLAN_DEEPSEEK_DISTILLATION.md) | Có hướng thực nghiệm/data training; chưa chứng minh model quality. Dataset contract và tool compliance phải bổ sung outcome/grounding; training data không được lấy từ held-out eval hoặc reasoning/feedback chưa duyệt. |

Đánh giá này **không sửa các plan**. Các mâu thuẫn trên cần được xử lý khi mở công việc tương ứng; PASS của docs validator không phát hiện toàn bộ mâu thuẫn ngữ nghĩa giữa tài liệu và từng orchestrator.

## 8. “Đạt chuẩn” cho project này nên được định nghĩa ra sao?

### 8.1. Các điều kiện bắt buộc trước pilot thật

| Gate | Điều kiện nghiệm thu có thể quan sát |
|---|---|
| Đúng và an toàn nghiệp vụ | Quyền/sở hữu từ session; không unconfirmed mutation; đề xuất khác transaction; lời báo thành công khớp DB acknowledgement; không bịa stock/order/policy. |
| Grounding | Policy claims có evidence phù hợp và citations hợp lệ; không evidence/thiếu điều kiện → abstain/clarify/handoff. Chấm semantic support độc lập với ID validation. |
| Runtime/retry | Cache đúng ngữ cảnh/revision; replay không trùng side effect; citation lỗi có đường retry hữu ích; lỗi quá tải/DB/provider theo contract; không leak slots. |
| Prompt/provider | Cùng base policy và tool scope; model/protocol/prompt/KB identity có version; data từ retrieval không được cấp quyền tool hoặc thay instruction. |
| Telemetry | Actual model attempts/results/tools/mode; queue/inference/tool/DB/total time riêng; known-zero khác unknown; token/cost không suy diễn từ HTTP 200. |
| Evaluation | Retrieval labels, expected task outcomes, multi-turn/adversarial/failure/load cases; raw case evidence và metadata đủ tái lập trên model thật. |
| Dữ liệu/vận hành | Corpus thật được chủ nghiệp vụ duyệt, applicability rõ; escalation có acknowledgement; retention/quyền đọc trace; monitoring và rollback cho pilot giới hạn. |

Các gate này vẫn cần thiết dù chọn single-agent hay multi-agent. GraphRAG, reranker, query rewrite, fine-tuning và microservices là phương án tối ưu, không phải checklist bắt buộc.

### 8.2. Ngưỡng chất lượng đề xuất ban đầu

Đây là **ngưỡng nội bộ để thảo luận/hiệu chuẩn**, không tuyên bố là chuẩn ngành hoặc đã đạt. Báo số mẫu, từng category, held-out riêng và khoảng tin cậy; số nhỏ không đủ kết luận khả năng tổng quát.

| Chỉ số | Đề xuất cho gate pilot |
|---|---|
| Ownership, unconfirmed writes, secret/data disclosure | **0 lỗi quan sát** trong critical regression/adversarial suite; không diễn giải thành rủi ro tuyệt đối bằng 0. |
| Citation provenance khi cần evidence | **100% hợp lệ**; policy zero-tool/no-evidence không được trả factual policy assertion. |
| Candidate retrieval Recall@5 | Khởi điểm **≥90%** trên tập có qrels. Đo riêng delivered-evidence Recall@3 vì tool chỉ trả tối đa 3 sources; kiểm mất recall sau truncate. |
| Supported/accurate policy claims | Khởi điểm **≥95%** theo nhãn reviewer; theo dõi unsupported high-impact claims và abstention precision/recall riêng. |
| Business task completion | Khởi điểm **≥90% tổng**, category trọng yếu không dưới **85%**; phải chấm backend outcome/clarification/handoff đúng, không chỉ prose hoặc HTTP 200. |
| Latency/overload/cost | SLO theo phần cứng/UX; đo queue, full response và retry overhead. Mục tiêu headroom `/healthz` P99 ≤50ms chỉ trong điều kiện test canonical plan, không là cam kết cho mọi tải. |

Không dùng LLM judge làm nguồn chấm duy nhất: kết hợp checks xác định cho IDs/tools/DB/citations, reviewer cho claim support và judge đã hiệu chuẩn. Có labels cho câu không nên trả lời để tránh nâng recall bằng cách luôn đoán.

## 9. Kế hoạch nâng hệ thống từ M1 lên M2

| Bước | Công việc đề xuất | Điều kiện kết thúc |
|---|---|---|
| **S1 — Correctness** | Thực thi PR A; thêm test LLM-02/03/04 vào đúng ranh giới hoặc PR tiếp nối rõ scope. Ép `orchestrator="multi_agent"` trong integration cases liên quan. | AC correctness và các negative/retry cases PASS; không response thành công giả hoặc policy không evidence. |
| **S2 — Runtime** | PR B sau A: HTTP admission, gate Q=5, telemetry, history, ToolCache epoch/CAS, OAuth. Thống nhất deadline/budget và actual trace. | Canonical status/header, slot recovery, in-flight invalidation và load matrix 1/2/4/8/16 có artifact; production path được kiểm. |
| **S3 — Grounding & tri thức** | Base prompt parity; policy evidence gate; KB revision/lifecycle; handoff acknowledgement; trace allowlist; sửa retry final/checkpoint. | LLM-02…09 có tests và corpus pilot được duyệt; phân biệt lịch sử với dữ kiện hiện hành. |
| **S4 — Evaluation thật** | Sửa grader; bổ sung qrels/gold outcomes/claim labels; chạy model thật cùng baseline, phiên multi-turn, failure/adversarial và canary. | Báo cáo quality + latency + cost tái lập, per-category; đạt gates mục 8, có review các ca lỗi. |
| **S5 — Pilot giới hạn** | Phạm vi khách/nghiệp vụ rõ, monitoring/handoff, release/rollback/recovery, người chịu trách nhiệm KB. | Có quyết định GO cho phạm vi cụ thể dựa trên artifact; chỉ tăng phạm vi khi số đo ổn định. |

Không cần hoàn thành mọi plan dài hạn mới bắt đầu pilot. PR C/schema mới, GraphRAG, MCP transport, fine-tuning và scale-out giữ là nhánh tùy nhu cầu. Không vừa thay retrieval, prompt, model và runtime trong một lần benchmark: khó biết cải thiện đến từ đâu.

### 9.1. Bộ evaluation cần bổ sung

1. **Retrieval:** query → relevant documents/chunks, tiếng Việt đa dạng, policy applicability, no-evidence; Recall@k/MRR/nDCG và recall sau tool budgets.
2. **Generation:** factual accuracy, supported claims, citation completeness, abstention, ambiguity và adversarial passages; label theo nguồn có version.
3. **Workflow:** expected tools/args và backend outcome; clarification, context switch, explicit confirmation, handoff failure, retry/restart. Không ép một tool sequence duy nhất nếu có nhiều cách đúng.
4. **Runtime:** đồng thời, overload/header, queue/deadline, mutation/cache race, history/replay; đo đúng total response và retry.
5. **So model:** cùng commit/prompt/corpus/dataset/grader/config; cache disabled cho phép so năng lực model, cache enabled trong run runtime riêng; lặp đủ để phản ánh stochastic variation.

Mỗi run lưu code SHA, dataset SHA, KB revision, model ID/digest khi có, provider/version/config, prompt/protocol/grader version, orchestrator, hardware, cache mode, timestamp và raw case trace đã kiểm dữ liệu nhạy cảm. Thiếu identity thì đánh dấu thiếu, không tự gán.

Giữ nguyên [frozen master 250](../evals/scenarios/master_250_v1.jsonl) và [mirror](../evals/scenarios/benchmark_250.jsonl); labels/test bổ sung ở tập riêng. Không dùng câu hỏi held-out để distill/fine-tune rồi báo kết quả như dữ liệu chưa thấy.

### 9.2. Khi nào mới nâng retrieval/model?

- Nếu paraphrase/đồng nghĩa làm Recall@k thấp: A/B multilingual neural embeddings với feature-hash baseline; migration index có model/version riêng.
- Nếu candidate đúng nhưng xếp hạng sai: thử fusion/reranker và đo gain/cost/latency.
- Nếu chunk mất ngoại lệ/điều kiện: sửa chunking/applicability trước tăng model size.
- Nếu lỗi là multi-hop quan hệ: thử relational linkage hoặc GraphRAG trên tập riêng; cần chứng minh lợi ích trước đưa vào runtime.
- Nếu lỗi vẫn là tool reasoning/format/ngôn ngữ sau khi runtime/grounding đã đúng: so model/prompt rồi cân nhắc fine-tuning từ dữ liệu đã duyệt.

## 10. Xác minh thực hiện trong lượt đánh giá

- Đã đọc các đường runtime quan trọng và đối chiếu plan, tests, CI/artifacts; các finding dựa trên snapshot `376322f`.
- Đã chạy kiểm tra tĩnh `python -B -X utf8 scripts/check_docs_contract.py`: **PASS 4/4**. Chỉ chứng minh các hợp đồng mà script kiểm: dataset integrity, metadata, links và tool AST; không chứng nhận chất lượng model/RAG.
- Không chạy suite runtime/DB, model live, load test hoặc deployment; chưa xác nhận các chất lượng/SLO được đề xuất.
- Chỉ tạo tài liệu đánh giá này; mã nguồn, dataset, các plan có sẵn, file review và execution handoff được giữ nguyên.

**Quyết định hiện tại:** phù hợp tiếp tục nghiên cứu/demo có kiểm soát; **chưa GO cho pilot nghiệp vụ thật hoặc production mở rộng**. Bước kế tiếp là triển khai correctness/runtime và bổ sung grounding/evaluation; chỉ thông báo M2 READY khi có kết quả nghiệm thu thực tế cho phạm vi pilot cụ thể.
