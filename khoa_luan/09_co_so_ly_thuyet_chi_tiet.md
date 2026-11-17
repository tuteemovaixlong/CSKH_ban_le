# Cơ sở lý thuyết chi tiết — đặc tả cho Chương 1

Tài liệu nội bộ (2026-11-17) cho người viết Chương 1. Owner chốt: **lý thuyết phải kỹ** vì hội đồng học thuật sẽ soi công thức, cách tính loss, nền tảng. Mỗi mục gồm: nội dung, công thức, dẫn xuất cần trình bày, **ví dụ số lấy từ chính hệ thống**, chỗ công thức được tính trong mã, và câu hỏi phản biện dự kiến kèm ý trả lời. Ký hiệu thống nhất cho cả khóa luận ở cuối tệp.

Thông số Qwen3.5-9B dùng cho ví dụ (config chính hãng): `hidden_size` $d = 4096$; 32 lớp, chu kỳ 3 lớp Gated DeltaNet + 1 lớp attention đầy đủ (24 + 8); attention đầy đủ: 16 head truy vấn, 4 head KV, `head_dim` 256, cổng đầu ra (`attn_output_gate`), RoPE từng phần 25% chiều, $\theta = 10^7$; DeltaNet: 16 head khóa, 32 head giá trị, chiều 128, tích chập ngắn kernel 4; MLP `intermediate_size` 12.288; từ vựng 248.320; 1 lớp MTP; RMSNorm $\epsilon = 10^{-6}$; ngữ cảnh gốc 262.144; phần nhìn ảnh 27 khối, 1.152 chiều.

---

## 1. Mô hình ngôn ngữ (≈ 4 trang)

### 1.1 Token hóa và mô hình hóa ngôn ngữ
- BPE mức byte: từ vựng $V$, $|V| = 248.320$; một chuỗi văn bản thành dãy $y_{1:n}$. Ký tự có dấu tiếng Việt thường tốn nhiều byte → nhiều token hơn tiếng Anh cùng nội dung; hệ thống giả định khoảng 2,6 ký tự/token khi tính ngân sách (36.000 ký tự cho cửa sổ 16.384 token, `agent_protocol.max_characters`). Ví dụ đo: system prompt (6.086 ký tự) + mô tả 12 tool + một câu khách = **2.892 token**.
- Phân rã tự hồi quy: $p_\theta(y_{1:n}) = \prod_{t=1}^{n} p_\theta(y_t \mid y_{<t})$, với $p_\theta(\cdot \mid y_{<t}) = \mathrm{softmax}(W_{\text{out}} h_t)$, $h_t \in \mathbb{R}^{d}$.
- Chat template: chuỗi hội thoại thành một văn bản có token đặc biệt `<|im_start|>role … <|im_end|>`, suy nghĩ trong `<think>…</think>`, gọi công cụ dạng `<tool_call><function=tên><parameter=khóa>giá trị</parameter></function></tool_call>`, kết quả công cụ trong `<tool_response>`. Mẫu thật in ở CELL 4 notebook smoke.
- **Phản biện:** "Vì sao không đếm token mà đếm ký tự?" → ngân sách ký tự tính được trước khi gọi model, không cần tokenizer ở tầng ứng dụng; tỉ lệ ký tự/token là giả định thiết kế, có biên an toàn 200 ký tự; hạn chế ghi ở 4.7.

### 1.2 Khối Transformer và attention
- Attention tích vô hướng có tỉ lệ: $\mathrm{Attn}(Q,K,V) = \mathrm{softmax}\!\left(\frac{QK^\top}{\sqrt{d_h}} + M\right)V$, $M_{ij} = -\infty$ nếu $j > i$ (mặt nạ nhân quả). Giải thích vì sao chia $\sqrt{d_h}$ (giữ phương sai của tích vô hướng ≈ 1 khi các thành phần độc lập phương sai 1).
- Đa đầu và **GQA**: 16 head truy vấn dùng chung 4 head KV (nhóm 4) → giảm KV cache 4 lần so với MHA. Kích thước ma trận thật: $W_Q \in \mathbb{R}^{8192 \times 4096}$ (16 × 256 cho truy vấn và 16 × 256 cho cổng), $W_K, W_V \in \mathbb{R}^{1024 \times 4096}$, $W_O \in \mathbb{R}^{4096 \times 4096}$.
- **Cổng đầu ra:** $o = \sigma(g) \odot \mathrm{Attn}(\cdot)$, $g$ là nửa sau đầu ra của $W_Q$.
- **RoPE từng phần:** quay cặp chiều $(x_{2i}, x_{2i+1})$ một góc $m\,\theta^{-2i/d_r}$ tại vị trí $m$, chỉ trên $d_r = 25\% \cdot 256 = 64$ chiều; tính chất $\langle R_m q, R_n k\rangle$ chỉ phụ thuộc $m - n$ (vị trí tương đối). $\theta = 10^7$ kéo dài bước sóng cho ngữ cảnh dài.
- **RMSNorm:** $\mathrm{RMSNorm}(x) = \frac{x}{\sqrt{\frac{1}{d}\sum_i x_i^2 + \epsilon}} \odot (1 + w)$ (dạng tâm 0, trọng số khởi tạo 0 tương đương nhân 1, như Qwen3-Next; trước khi viết, kiểm lại trong mã `Qwen3_5RMSNorm` của transformers 5.17).
- **MLP SwiGLU:** $\mathrm{MLP}(x) = W_{\text{down}}\big(\mathrm{SiLU}(W_{\text{gate}}x) \odot W_{\text{up}}x\big)$, $4096 \to 12288 \to 4096$.
- Khối pre-norm có phần dư: $x' = x + \mathrm{Attn}(\mathrm{Norm}(x))$, $x'' = x' + \mathrm{MLP}(\mathrm{Norm}(x'))$.

### 1.3 KV cache và attention tuyến tính Gated DeltaNet
- **KV cache** mỗi token $= 2 \cdot L_{\text{attn}} \cdot n_{kv} \cdot d_h \cdot b$. Với 8 lớp attention, 4 head KV, 256 chiều, bf16 ($b = 2$): $2 \cdot 8 \cdot 4 \cdot 256 \cdot 2 = 32.768$ byte = **32 KiB/token**; một chuỗi 32k token ≈ **1 GiB**. Nếu cả 32 lớp là attention đầy đủ: 4 GiB. Đây là lý do kiến trúc lai chạy 8 luồng song song trên L4 24 GB.
- **Gated DeltaNet** [Yang 2025]: trạng thái ma trận $S_t \in \mathbb{R}^{d_v \times d_k}$ mỗi head, cập nhật theo luật delta có cổng
  $S_t = \alpha_t\, S_{t-1}\big(I - \beta_t k_t k_t^\top\big) + \beta_t v_t k_t^\top$, $o_t = S_t q_t$,
  với $\alpha_t \in (0,1)$ là cổng quên (từ `in_proj_a`), $\beta_t \in (0,1)$ là tốc độ ghi (từ `in_proj_b`), $q,k,v$ từ `in_proj_qkv` sau tích chập ngắn kernel 4, cổng đầu ra $z$ (`in_proj_z`) qua RMSNorm có cổng. Giải thích trực giác: $(I - \beta k k^\top)$ xóa thông tin cũ theo hướng $k$ rồi ghi giá trị mới — học hồi quy trực tuyến.
- Độ phức tạp: attention đầy đủ $O(n^2 d)$ thời gian, bộ nhớ KV $O(n)$; DeltaNet $O(n\, d_k d_v)$ thời gian, trạng thái **cố định** $32 \cdot 128 \cdot 128$ phần tử mỗi lớp (≈ 1 MiB bf16), 24 lớp ≈ 24 MiB mỗi chuỗi, không tăng theo $n$.
- **Phản biện:** "Lai thì mất gì?" → lớp tuyến tính nén lịch sử vào trạng thái cố định nên kém truy xuất chính xác từ xa; 8 lớp attention đầy đủ giữ khả năng đó.

### 1.4 Giải mã và lấy mẫu
- Nhiệt độ: $p_i = \frac{\exp(z_i / T)}{\sum_j \exp(z_j / T)}$; top-k giữ $k$ logit lớn nhất; top-p (nucleus) giữ tập nhỏ nhất có tổng xác suất ≥ $p$; presence penalty $z_i \leftarrow z_i - \lambda\,\mathbb{1}[i \text{ đã xuất hiện}]$. Bộ tham số thật (W6.4-D10): $T = 1{,}0$, top-p 0,95, top-k 20, $\lambda = 1{,}5$; `max_tokens` 2048.
- Vì sao không dùng $T = 0$ cho Qwen thinking: khuyến nghị của nhóm Qwen, tránh lặp vô hạn trong suy nghĩ; hệ quả là kết quả ngẫu nhiên → phải chạy 3 lần và báo pass^3.

### 1.5 Giải mã suy đoán và MTP
- Model nháp đề xuất $\hat{x}$ với phân phối $q$; model chính có $p$. Chấp nhận với xác suất $\min\!\big(1, p(\hat{x})/q(\hat{x})\big)$; nếu từ chối, lấy mẫu từ $p'(x) = \frac{\max(0, p(x) - q(x))}{\sum_y \max(0, p(y) - q(y))}$. **Dẫn xuất ngắn** [Leviathan 2023]: $\Pr[\text{ra } x] = q(x)\min(1, p(x)/q(x)) + (1 - \beta)p'(x) = \min(q(x), p(x)) + \max(0, p(x) - q(x)) = p(x)$ → đầu ra **cùng phân phối** với giải mã thường. Hệ quả cho khóa luận: MTP không đổi chất lượng, chỉ đổi tốc độ.
- vLLM lấy token nháp = argmax của đầu MTP ($q$ là phân phối suy biến) → xác suất chấp nhận = $p(\hat{x})$.
- Với 2 token nháp, số token sinh mỗi bước kỳ vọng $E = 1 + a_1 + a_1 a_2$. Số thật W6.4: $E = 2{,}28$, smoke đo $a_1 = 0{,}81$ → $a_2 \approx 0{,}58$; tỉ lệ chấp nhận trung bình $(a_1 + a_1 a_2)/2 = 0{,}64$ khớp số vLLM 64,0%.
- Đầu MTP của Qwen3.5 [Gloeckle 2024; mã vLLM `qwen3_5_mtp.py`]: $x = W_{fc}\,[\mathrm{Norm}_e(E(y_{t+1}));\ \mathrm{Norm}_h(h_t)]$, $W_{fc} \in \mathbb{R}^{4096 \times 8192}$ → một lớp attention đầy đủ → Norm → $W_{\text{out}}$ dùng chung → đoán $y_{t+2}$. 243,3 triệu tham số.
- Ở mã: `scratch/colab_w67_lora_smoke_cells.py` CELL 9–10 (M26).

## 2. Học có giám sát, hàm mất mát và tối ưu (≈ 4 trang) — phần hội đồng soi nhiều nhất

### 2.1 Entropy chéo, KL và perplexity
- Với phân phối đích $p^*$ (one-hot tại token đúng $y_t$) và dự đoán $p_\theta$: $H(p^*, p_\theta) = -\sum_v p^*(v)\log p_\theta(v) = -\log p_\theta(y_t \mid y_{<t})$.
- $H(p, q) = H(p) + \mathrm{KL}(p \,\|\, q)$ → cực tiểu entropy chéo tương đương cực tiểu KL tới phân phối dữ liệu; tương đương **ước lượng hợp lý cực đại**.
- Perplexity $= \exp(\mathcal{L})$ (đơn vị nats). Ví dụ smoke: loss bước đầu 1,33 → PPL ≈ 3,8.
- Gradient theo logit: $\frac{\partial \mathcal{L}}{\partial z_v} = p_\theta(v) - \mathbb{1}[v = y_t]$ — dẫn ra từ softmax, giải thích vì sao entropy chéo + softmax ổn định số học (dùng log-sum-exp).

### 2.2 Loss của SFT có mặt nạ — **tính chính xác như thế nào**
- Đầu vào là toàn bộ hội thoại đã dựng bằng chat template, mã thành $y_{1:n}$. Nhãn $\ell_t = y_t$ nếu token $t$ thuộc phần trợ lý (suy nghĩ, lời gọi tool, câu trả lời, kể cả `<|im_end|>` kết thúc lượt), ngược lại $\ell_t = -100$ (bỏ qua).
- **Dịch nhãn:** logit tại vị trí $t$ dự đoán token $t+1$. Thư viện tính trên `logits[:, :-1]` và `labels[:, 1:]`.
- Loss: $\mathcal{L} = \dfrac{\sum_{t=1}^{n-1} m_{t+1}\,\big(-\log p_\theta(y_{t+1} \mid y_{\le t})\big)}{\sum_{t} m_{t+1}}$, $m_t = \mathbb{1}[\ell_t \ne -100]$.
- Vì sao mặt nạ: không dạy model sinh system prompt, mô tả tool, lời khách, kết quả tool (không phải hành vi của nó); tập trung gradient vào hành vi trợ lý. Số thật smoke: **85 / 3.007 token** mang nhãn.
- **Chuẩn hóa khi gộp lô và tích lũy gradient:** nếu lấy trung bình trong từng mẫu rồi trung bình các mẫu, mẫu ngắn bị đánh trọng số cao hơn mỗi token; đúng là chia cho **tổng số token có nhãn của cả bước tối ưu** (transformers ≥ 4.46 dùng `num_items_in_batch`). Ghi rõ lựa chọn dùng trong notebook huấn luyện.
- Ở mã: `assistant_mask` (M25) dựng $m_t$ bằng `offset_mapping`; loss do `model(input_ids, labels)` tính (Unsloth dùng entropy chéo hợp nhất theo khối để không tạo ma trận logit $n \times 248.320$ đầy đủ — với $n = 5.503$ token, ma trận đó bf16 tốn ≈ 2,7 GB).
- **Phản biện:** "Loss xuống 0,0002 là học tốt?" → không: 8 mẫu gần trùng nhau nên model thuộc lòng; chỉ chứng minh mặt nạ và gradient đúng. Chất lượng đánh giá bằng loss trên tập kiểm tra và bằng 250 ca.

### 2.3 Chưng cất tri thức
- KD mức logit [Hinton 2015]: $\mathcal{L} = (1-\lambda)\,\mathrm{CE}(y, p_S) + \lambda\,\tau^2\,\mathrm{KL}\big(p_T^{(\tau)} \,\|\, p_S^{(\tau)}\big)$; giải thích hệ số $\tau^2$ (giữ độ lớn gradient khi làm mềm).
- KD mức chuỗi [Kim & Rush 2016]: học trò cực đại $\log p_S(\hat{y})$ với $\hat{y}$ là chuỗi thầy sinh — tương đương xấp xỉ phân phối thầy bằng mode.
- **Vì sao đề tài dùng mức chuỗi:** API DeepSeek không trả phân phối đầy đủ và dùng tokenizer khác Qwen → không tính được KL theo token; chỉ có văn bản quỹ đạo. Quỹ đạo của chính Qwen thì cùng tokenizer nhưng ta chỉ giữ quỹ đạo đạt (mục 2.4).

### 2.4 Lấy mẫu loại bỏ và tự sinh dữ liệu
- Phần thưởng nhị phân $R(\tau) \in \{0, 1\}$: 1 khi quỹ đạo qua mọi kiểm tra của ca (tool, hành động, trạng thái cuối, cụm chữ) và tier A. Phân phối được chấp nhận $\pi_{\text{acc}}(\tau) \propto \pi(\tau)\,R(\tau)$.
- SFT trên mẫu chấp nhận cực đại $\mathbb{E}_{\tau \sim \pi_{\text{acc}}}[\log \pi_\theta(\tau)]$ — một bước cải tiến chính sách kiểu expert iteration; liên hệ gradient chính sách với phần thưởng 0/1: $\nabla J = \mathbb{E}_\pi[R(\tau)\nabla \log \pi_\theta(\tau)]$ — SFT trên mẫu đạt là ước lượng có trọng số đều của số hạng này [STaR; RFT].
- Xác suất có ít nhất một mẫu đạt sau $k$ lần thử độc lập của một ca có tỉ lệ đạt $p_i$: $1 - (1-p_i)^k$. **Bẫy cần nêu:** nếu dùng tỉ lệ trung bình $\bar{p} \approx 0{,}58$ thì $1 - 0{,}42^4 \approx 97\%$, nhưng độ khó không đồng đều giữa các ca: ở W6.4, **77/250 ca (31%) không đạt lần nào trong 3 lần** theo bộ chấm chính thức, nên tỉ lệ ca có ít nhất một quỹ đạo Qwen đạt thấp hơn nhiều so với 97% (phải tính $\frac{1}{N}\sum_i [1 - (1-p_i)^k]$ theo từng ca). Đây là lý do chọn $k = 4$ cho Qwen và dùng DeepSeek ($k = 2$) lấp các ca Qwen không đạt.
- Rủi ro thiên lệch: lấy mẫu loại bỏ ưu tiên ca dễ → phễu dữ liệu phải báo phân bố số bước gọi tool, độ dài, theo khung (4.5).

### 2.5 LoRA
- $W' = W_0 + \Delta W$, $\Delta W = \frac{\alpha}{r} B A$, $A \in \mathbb{R}^{r \times d_{in}}$ (khởi tạo ngẫu nhiên), $B \in \mathbb{R}^{d_{out} \times r}$ (khởi tạo 0 → $\Delta W = 0$ lúc đầu, model y hệt bản gốc), $W_0$ đóng băng.
- Gradient: $\frac{\partial \mathcal{L}}{\partial B} = \frac{\alpha}{r}\,G\,(A x)^\top$, $\frac{\partial \mathcal{L}}{\partial A} = \frac{\alpha}{r}\,B^\top G\, x^\top$ với $G = \partial \mathcal{L}/\partial y$.
- **Đếm tham số bằng tay — khớp tuyệt đối số smoke (43.278.336):** mỗi lớp LoRA có $r(d_{in} + d_{out})$ tham số, $r = 16$:
  - Attention (8 lớp): $q$ $16(4096 + 8192) = 196.608$; $k$, $v$ mỗi cái $16(4096 + 1024) = 81.920$; $o$ $16(4096 + 4096) = 131.072$ → 491.520/lớp → **3.932.160**.
  - MLP (32 lớp): gate, up, down mỗi cái $16(4096 + 12288) = 262.144$ → 786.432/lớp → **25.165.824**.
  - Gated DeltaNet (24 lớp): `in_proj_qkv` $16(4096 + 8192) = 196.608$ (q 2.048 + k 2.048 + v 4.096); `in_proj_z` $16(4096 + 4096) = 131.072$; `in_proj_a`, `in_proj_b` mỗi cái $16(4096 + 32) = 66.048$; `out_proj` 131.072 → 590.848/lớp → **14.180.352**.
  - Tổng $3.932.160 + 25.165.824 + 14.180.352 = $ **43.278.336** = 0,46% của 9,45 tỷ.
- Vì sao hạng thấp đủ: giả thuyết chiều nội tại thấp của tinh chỉnh [Aghajanyan 2021; Hu 2022]; vai trò $\alpha/r = 2$.
- **Bộ nhớ:** fine-tune toàn phần với Adam ≈ 16 byte/tham số (trọng số bf16 2 + bản fp32 4 + gradient 2 + hai mô-men fp32 8) → $9{,}45 \cdot 10^9 \times 16 \approx 151$ GB, không vừa A100 40 GB. LoRA: trọng số bf16 ≈ 18,9 GB + LoRA và trạng thái Adam ≈ 0,7 GB + kích hoạt → đỉnh đo 18,9–23 GB.
- Gộp: $W_{\text{merge}} = W_0 + \frac{\alpha}{r}BA$, cùng kích thước → suy luận không tốn thêm.

### 2.6 Tối ưu
- AdamW: $m_t = \beta_1 m_{t-1} + (1-\beta_1)g_t$, $v_t = \beta_2 v_{t-1} + (1-\beta_2)g_t^2$, $\hat{m}_t = m_t/(1-\beta_1^t)$, $\hat{v}_t = v_t/(1-\beta_2^t)$, $\theta_t = \theta_{t-1} - \eta\big(\hat{m}_t/(\sqrt{\hat{v}_t} + \epsilon) + \lambda_{wd}\theta_{t-1}\big)$ (suy giảm trọng số tách rời).
- Lịch học: khởi động tuyến tính rồi giảm (cosine hoặc tuyến tính); cắt gradient theo chuẩn $g \leftarrow g \cdot \min(1, c/\|g\|)$.
- **Bằng chứng từ smoke MTP:** lr $10^{-4}$ không khởi động làm loss vọt 1,22 → 5,77 trên đầu MTP đã gần tối ưu → giải thích bằng bước đầu của Adam: $\hat{m}_1/\sqrt{\hat{v}_1} = \mathrm{sign}(g_1)$, mọi tham số dịch đúng $\eta$ bất kể độ lớn gradient → chọn lr ~$10^{-5}$ có khởi động.
- bf16 (8 bit mũ như fp32, 7 bit trị) và lý do không cần loss scaling; checkpoint gradient (tính lại kích hoạt khi lan truyền ngược, đổi thời gian lấy bộ nhớ); Unsloth đẩy kích hoạt sang RAM máy.

### 2.7 Tự chưng cất đầu MTP
- Mục tiêu: $\mathcal{L}_{\text{MTP}} = -\frac{1}{|T|}\sum_{t \in T}\sum_{v \in \mathcal{K}_t}\tilde{p}_{t+1}(v)\log q_t(v)$, $\tilde{p}_{t+1}$ là phân phối của model chính đã gộp tại vị trí $t+1$ sau top-k 20 / top-p 0,95 (đúng tham số lấy mẫu), $q_t$ là phân phối của đầu MTP. Bằng $\mathrm{KL}(\tilde{p} \,\|\, q) + H(\tilde{p})$ → cực tiểu KL.
- Vì sao dùng nhãn mềm thay token thật: tỉ lệ chấp nhận phụ thuộc $p(\arg\max q)$, nên phải khớp phân phối của chính model phục vụ, không phải dữ liệu.
- Chỉ số theo dõi: $\hat{a}_1 = \frac{1}{|T|}\sum_t \tilde{p}_{t+1}(\arg\max_v q_t(v))$ (đầu gốc trên model gốc: 0,81).

## 3. Tác tử, máy trạng thái và gọi công cụ (≈ 2 trang)

### 3.1 Mô hình hóa
- POMDP $(\mathcal{S}, \mathcal{A}, \mathcal{O}, T, R)$: trạng thái CSDL ẩn với model; model chỉ thấy quan sát qua tool; chính sách theo lịch sử $\pi_\theta(a_t \mid h_t)$; phần thưởng là kiểm tra cuối ca (thưa, nhị phân).
- Ràng buộc $\mathcal{C}$ thực thi bằng code, không bằng phần thưởng.

### 3.2 Máy trạng thái và LangGraph
- Đồ thị $G = (V, E)$; trạng thái $s \in \mathcal{S}$ là bản ghi kiểu (TypedDict); nút $f_v: \mathcal{S} \to \mathcal{S}$; cạnh có điều kiện $g_v: \mathcal{S} \to V \cup \{\text{END}\}$; thực thi theo bước (superstep): chạy nút → cập nhật kênh trạng thái → lưu checkpoint → chọn nút kế; giới hạn đệ quy 32 bước.
- Agent-first: $V = \{\text{guard}, \text{model}, \text{tools}\}$, $g(s) = \text{END}$ nếu $s.\text{complete}$, ngược lại nút kế cố định. Chứng minh dừng: mỗi vòng model tăng `model_calls`, chặn tại 6 → số bước hữu hạn $\le 1 + 2 \cdot 6$.
- Checkpoint: điểm khôi phục sau mỗi nút → chạy tiếp sau lỗi mà không gọi lại tool đã chạy; khóa thuê bảo đảm một lượt chỉ một tiến trình (loại trừ lẫn nhau).

### 3.3 Gọi công cụ theo JSON Schema
- Schema: `type: object`, `properties`, `required`, `additionalProperties: false`, `enum`, `minimum`/`maximum`, `maxLength`; kiểm hợp lệ là bài toán quyết định tất định trên cấu trúc JSON.
- Parser `qwen3_coder` chuyển khối XML-like của model thành `{"name", "arguments"}`; lỗi định dạng → không chạy (fail-closed).
- ReAct [Yao 2023]: xen kẽ suy nghĩ – hành động – quan sát; vì sao lần gọi cuối không gửi tool (bảo đảm có câu trả lời) và hệ quả F52.

## 4. Biểu diễn văn bản, CSDL vector và truy hồi (≈ 3 trang)

### 4.1 Không gian vector và độ tương đồng
- Cosine $\cos(u, v) = \frac{u^\top v}{\|u\|\|v\|}$; với vector chuẩn hóa L2, $\cos = u^\top v$ và $\|u - v\|^2 = 2 - 2\cos$ → xếp hạng theo cosine ≡ theo khoảng cách Euclid. pgvector: `<=>` là khoảng cách cosine $1 - \cos$.

### 4.2 Feature hashing — embedding thật của hệ thống
- Đặc trưng $f$ (từ đơn trọng số 1,0; cặp từ liền nhau 1,35; 3-gram ký tự của từ ≥ 5 ký tự 0,30). Hàm băm $h: \mathcal{F} \to \{0, \dots, 383\}$ và dấu $\xi: \mathcal{F} \to \{\pm 1\}$ lấy từ BLAKE2b 8 byte.
- $\phi_j(x) = \sum_{f:\,h(f) = j} \xi(f)\,w_f\,c_f(x)$, sau đó chuẩn hóa L2.
- **Tính không chệch** [Weinberger 2009]: $\mathbb{E}_\xi[\langle\phi(x), \phi(x')\rangle] = \langle x, x'\rangle$ vì số hạng chéo của hai đặc trưng khác nhau rơi cùng ô có kỳ vọng $\mathbb{E}[\xi(f)\xi(f')] = 0$; phương sai giảm theo $1/d$. Dấu ± chính là để khử chệch do va chạm.
- **Bản chất:** biểu diễn từ vựng/ký tự; "hủy đơn" và "bỏ đơn" chỉ gần nhau nếu chung từ "đơn" — không nắm đồng nghĩa. 3-gram ký tự giúp chịu lỗi chính tả ("huy don" vs "hủy đơn" vẫn khác vì dấu; chuẩn hóa NFKC không bỏ dấu). So với embedding neural (E5) chỉ làm đối chứng ở thí nghiệm E1.
- **Vì sao hệ thống chọn feature hashing (quyết định của owner, 17/11):** tạo vector là vài phép băm trên đặc trưng của câu, $O(|q|)$, chạy ngay trong tiến trình Python, không GPU, không tải model hàng trăm MB, không phụ thuộc mạng; kết quả tất định nên tái lập được tuyệt đối; lược đồ pgvector giữ nguyên nếu sau này thay embedding. Cái giá: không nắm đồng nghĩa và diễn đạt khác từ vựng; bù một phần bằng kênh từ vựng `ts_rank_cd` và cặp từ, 3-gram ký tự. Trình bày như một đánh đổi độ phủ – (độ tin cậy vận hành, tất định, độ trễ), có số đo ở 4.2; lưu ý trung thực: độ trễ truy hồi rất nhỏ so với độ trễ sinh của LLM (p50 lượt 29,6 s), nên lợi thế chính là không phụ thuộc dịch vụ ngoài.
- Bộ lọc "phải có ít nhất một từ chung" ở `KnowledgeTool.search` để loại kết quả chỉ do va chạm băm.

### 4.3 Tìm kiếm từ vựng
- BM25 [Robertson 2009]: $\mathrm{score}(q, d) = \sum_{t \in q}\mathrm{IDF}(t)\frac{f_{t,d}(k_1 + 1)}{f_{t,d} + k_1(1 - b + b\,|d|/\overline{|d|})}$ — trình bày làm nền.
- Hệ thống dùng `ts_rank_cd` của PostgreSQL (xếp hạng mật độ phủ — cover density [Clarke 2000]): điểm cao khi các từ truy vấn xuất hiện gần nhau; cấu hình `'simple'` (không tách gốc từ, phù hợp tiếng Việt vì PostgreSQL không có bộ tách từ tiếng Việt). Điểm không chặn trên → cắt $\min(s_{\text{lex}}, 1)$.

### 4.4 Truy hồi lai
- $s_\alpha = \alpha\,s_{\text{vec}} + (1 - \alpha)\min(s_{\text{lex}}, 1)$, hiện $\alpha = 0{,}75$; quét $\alpha \in \{0; 0{,}25; 0{,}5; 0{,}75; 1\}$ ở E1, chọn trên dev, báo trên held_out.
- Ngưỡng điểm tối thiểu; top-5 ứng viên; tối đa số nguồn trả về; ngân sách ký tự.

### 4.5 CSDL vector và chỉ mục ANN
- Định nghĩa: lưu vector kèm siêu dữ liệu, truy vấn k láng giềng gần nhất theo độ đo; tìm chính xác $O(Nd)$; tìm gần đúng đánh đổi độ phủ lấy tốc độ.
- **HNSW** [Malkov 2018]: đồ thị nhiều tầng, mỗi điểm ở tầng $\ell$ với xác suất giảm theo hàm mũ; tìm tham lam từ tầng trên xuống; độ phức tạp tìm kiếm kỳ vọng $O(\log N)$; tham số pgvector mặc định `m = 16`, `ef_construction = 64`, `hnsw.ef_search = 40`.
- Nhận xét trung thực: kho hiện chỉ vài chục đoạn (14 tài liệu) nên ANN gần như tìm chính xác; chỉ mục HNSW là thiết kế cho quy mô lớn hơn (nhiều cửa hàng, nhiều tài liệu).
- pgvector so với CSDL vector chuyên dụng: chỉ một đoạn văn trong 2.9 (một CSDL, giao dịch, phân quyền theo schema).

### 4.6 RAG và trích dẫn
- RAG [Lewis 2020]: $p(y \mid q) \approx p_\theta(y \mid q, D_k(q))$ với $D_k$ là top-k đoạn.
- Chia đoạn: kích thước $c = 900$ ký tự, chồng lấn $o = 140$ → số đoạn ≈ $\lceil (|doc| - o)/(c - o) \rceil$; chồng lấn giảm rủi ro cắt ngang câu chứa điều kiện chính sách.
- Trích dẫn kiểm được: mã `KB:<băm>` gắn với đoạn trả về trong lượt; kiểm **nguồn gốc** (provenance), không kiểm suy diễn (entailment) — phân biệt rõ.

## 5. An toàn của hệ tác tử (≈ 1 trang)
- Chèn lệnh trực tiếp và gián tiếp [Greshake 2023]: dữ liệu (tài liệu, PDF, kết quả tool) bị model hiểu nhầm là lệnh. Bài toán "kẻ trung gian bị lợi dụng" (confused deputy).
- Nguyên tắc: đặc quyền tối thiểu, ranh giới tin cậy, fail-closed, con người phê duyệt hành động không đảo ngược.
- Vì sao prompt không đủ: chính sách của model là xác suất, tồn tại đầu vào làm vi phạm với xác suất dương; ràng buộc trong code là bất biến tất định.
- OWASP LLM Top 10 (LLM01 prompt injection, LLM02 lộ thông tin, LLM06 quyền hành động quá mức…) đối chiếu biện pháp ở 2.6.

## 6. Đánh giá, thống kê và độ tin cậy của nhãn (≈ 2 trang)
- **pass@1** $= \frac{1}{N k}\sum_i c_i$ ($c_i$ số lần đạt trên $k$ lần của ca $i$); **pass^k** [Yao 2024] $= \frac{1}{N}\sum_i \binom{c_i}{k}/\binom{k}{k} = $ tỉ lệ ca đạt cả $k$ lần (với $n = k = 3$). Giải thích vì sao pass^k đo độ ổn định.
- Recall@k $= \frac{|\mathrm{Rel} \cap \mathrm{Top}_k|}{|\mathrm{Rel}|}$; MRR $= \frac{1}{|Q|}\sum_q \frac{1}{\mathrm{rank}_q}$ (0 nếu không có nguồn đúng trong top).
- **Bootstrap phân vị** [Efron 1979]: lấy mẫu có hoàn lại $B = 10.000$ lần trên các ca (đơn vị lấy mẫu là ca, không phải lượt, vì 3 lượt của một ca không độc lập), khoảng 95% là phân vị 2,5% và 97,5%; seed 20261110.
- **McNemar chính xác** cho dữ liệu cặp (cùng ca, trước/sau): $b$ = số ca chỉ trước đạt, $c$ = số ca chỉ sau đạt; dưới $H_0$, $b \sim \mathrm{Binomial}(b + c, 1/2)$; $p = \min\!\big(1, 2\sum_{i=0}^{\min(b,c)}\binom{b+c}{i}2^{-(b+c)}\big)$. Giải thích vì sao không dùng kiểm định tỉ lệ độc lập (hai mẫu không độc lập). Kết quả mỗi ca lấy theo đa số 3 lần.
- **Cohen's kappa** $\kappa = \frac{p_o - p_e}{1 - p_e}$, $p_e = \sum_k p_{1k}p_{2k}$; diễn giải theo thang Landis–Koch.
- **LLM làm giám khảo** [Zheng 2023]: thiên lệch vị trí, độ dài, tự ưu ái; biện pháp của đề tài: gói mù, hai nhóm độc lập, trích dẫn được code kiểm, gộp bảo thủ, kiểm định mẫu.
- **Jaccard** trên tập 5-gram ký tự $J(A, B) = \frac{|A \cap B|}{|A \cup B|}$, ngưỡng 0,45 với 250 ca, 0,7 trong cùng khung; chuỗi con chung ≥ 40 ký tự → loại (chống rò rỉ dữ liệu đo vào dữ liệu huấn luyện).
- Mối đe dọa tính hợp lệ: nội tại, ngoại tại, cấu trúc (construct), kết luận thống kê — khung để viết 4.7.

## 7. Ký hiệu dùng chung

| Ký hiệu | Nghĩa |
|---|---|
| $y_{1:n}$, $V$ | dãy token, từ vựng |
| $\pi_\theta$, $p_\theta$ | chính sách / phân phối của model tham số $\theta$ |
| $h_t$, $a_t$, $o_t$, $\tau$ | lịch sử, hành động, quan sát, quỹ đạo |
| $m_t$ | mặt nạ nhãn (1 với token trợ lý) |
| $W_0$, $A$, $B$, $r$, $\alpha$ | trọng số gốc, ma trận LoRA, hạng, hệ số |
| $p$, $q$, $a_1$, $a_2$ | phân phối model chính, đầu nháp, tỉ lệ chấp nhận bước 1, 2 |
| $s_{\text{vec}}$, $s_{\text{lex}}$, $s_\alpha$ | điểm vector, từ vựng, lai |
| $b$, $c$ | số ca lệch cặp trong McNemar |
| $R(\tau)$ | phần thưởng nhị phân của lấy mẫu loại bỏ |

## 8. Câu hỏi phản biện dự kiến (luyện trước khi bảo vệ)

1. Loss tính trên những token nào, chuẩn hóa thế nào khi gộp lô? → mục 2.2.
2. Vì sao không chưng cất theo logit của DeepSeek? → 2.3 (API không trả phân phối, khác tokenizer).
3. LoRA 43,3 triệu tham số tính ra sao? → 2.5 (đếm tay khớp tuyệt đối).
4. MTP có làm đổi câu trả lời không? → 1.5 (dẫn xuất bảo toàn phân phối).
5. Embedding của em có phải ngữ nghĩa không, sao không dùng neural? → 4.2 (không; là biểu diễn từ vựng chọn có chủ đích vì độ trễ, không GPU, tất định; E1 cho số đánh đổi so với neural).
6. Vì sao cần HNSW khi chỉ có vài chục đoạn? → 4.5 (thiết kế cho quy mô; hiện gần như chính xác).
7. Vì sao McNemar mà không phải t-test? → 6 (dữ liệu cặp nhị phân).
8. Tỉ lệ qua của giám khảo LLM tin được không? → 6 (kappa, kiểm định mẫu, gộp bảo thủ).
9. Lấy mẫu loại bỏ có làm lệch sang ca dễ không? → 2.4 và phễu 4.5.
10. Vì sao lr nhỏ cho đầu MTP? → 2.6 (bước đầu của Adam).
11. Vì sao kiến trúc lai chạy được 8 luồng trên 24 GB? → 1.3 (KV cache 32 KiB/token chỉ ở 8 lớp).
12. Tác tử có chắc dừng không? → 3.2 (chứng minh dừng bằng ngân sách).
