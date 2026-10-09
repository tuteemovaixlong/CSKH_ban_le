# AI Model Card

## Identity and provider paths

| Thành phần | Giá trị trích xuất |
|---|---|
| Local default | `qwen3.5:4b` từ cấu hình ([`config.py#L68-L76`](../../retailops/config.py#L68)) |
| API default | `meta/muse-spark-1.3-contributor` ([`retailops_providers.py#L23-L24`](../../retailops_providers.py#L23)) |
| API routing | Key/model/env chọn Anthropic, Google hoặc OpenRouter endpoint ([`retailops_providers.py#L114-L146`](../../retailops_providers.py#L114)) |
| Colab vLLM | Gemma 4 12B identifier trong notebook ([`colab_vllm_l4.py#L3-L5`](../../notebooks/colab_vllm_l4.py#L3)) |
| Model digest | Local Ollama yêu cầu digest để version hóa lượt chạy ([`retailops_baseline.py#L147-L158`](../../retailops_baseline.py#L147)) |

## Inference contract

- Native request dùng `stream=false`, `think=false`, `keep_alive=10m`, `temperature=0.2`, `seed=42` ([`agent_protocol.py#L359-L391`](../../agent_protocol.py#L359)).
- Local baseline mặc định temperature `0.0`, timeout `180s`; đây là baseline adapter, không phải bằng chứng production ([`retailops_baseline.py#L90-L100`](../../retailops_baseline.py#L90)).
- Context/model/tool budgets là 40 messages, 18,000 characters, 8 tool calls và 4 model calls ([`agent_protocol.py#L6-L10`](../../agent_protocol.py#L6)).

## Cost, latency, deployment

- API trace chỉ đặt chi phí 0 cho provider OpenRouter; provider khác để `None` nếu chưa có dữ liệu cost ([`graph.py#L117-L132`](../../retailops/workflow/graph.py#L117)).
- Latency được ghi vào trace từ thời gian thực thi graph ([`graph.py#L149-L153`](../../retailops/workflow/graph.py#L149)).
- [UNVERIFIED] Giá thực tế, P50/P95/P99, model revision đang deploy, quantization, throughput và endpoint G2; không có claim từ code này.

Nguồn tổng hợp: [MODELS digest](../_digest/code/MODELS.digest) và [AGENTS digest](../_digest/code/AGENTS.digest).
