# PostgreSQL + RAG — 0.10

Bước này hoàn thiện kho dữ liệu và luồng tra tài liệu. Chưa kết luận chất lượng model,
độ trễ production hay chi phí vận hành từ các test hợp đồng.

## Thành phần

- PostgreSQL 16 + pgvector 0.8.6 cùng EC2 CPU hiện có, không mở cổng 5432 ra host.
- Orders, identity, proposals, audit và LangGraph checkpoint vẫn theo schema đã có.
- Mỗi tenant có collection tài liệu riêng; HTTP và model không được chọn tenant/schema.
- Embedding quantized multilingual MiniLM-L12-v2, 384 chiều, ONNX CPU (FastEmbed).
- Operator tải model một lần, khóa revision và SHA256 từng file trong manifest.
  Web chỉ đọc model đã chuẩn bị; không tự tải, không gọi API embedding/Colab.
- Operator duyệt và publish toàn bộ collection. Validation và embedding hoàn tất trước
  transaction thay collection; lỗi không xóa collection đang dùng.
- `search_knowledge` trả tối đa 3 đoạn, cosine >= 0.5. Đây là ngưỡng khởi đầu chưa hiệu chuẩn.
  Exact search phù hợp collection demo nhỏ (tối đa 100 tài liệu/500 đoạn).
- Model dẫn `[K1]`, `[K2]`; backend kiểm tra mã dẫn nguồn và generation trước khi commit lượt chat.
  UI hiển thị tên, phiên bản và đoạn trích dưới câu trả lời bằng text thuần.
- Nguồn trích dẫn hợp lệ không chứng minh mọi câu trả lời được nguồn hỗ trợ; cần evaluation
  riêng cho faithfulness, retrieval và prompt injection. Tài liệu không cấp quyền hủy đơn.

`data/knowledge/demo.json` chỉ chứa chính sách **giả lập** đã đánh dấu `approved: true`.
Thông tin chất liệu đang thiếu vẫn được giữ là chưa biết. Không đưa chính sách thật hoặc
nội dung crawl tự động vào collection này mà chưa duyệt.

## 1. Chuyển web SQLite hiện tại sang PostgreSQL

Merge PR, chờ CD có image 0.10 trong `/opt/retailops/deployed.env`. Chạy tại **EC2 Session Manager**.
Bộ chuyển đổi kiểm tra phiên bản image, dừng web, sao lưu dữ liệu, import rồi kiểm tra health.
Nếu đang ở guest mode và vẫn còn guest workspace, script dừng trước khi thay đổi; không tự gộp dữ liệu khách.
Nếu không còn workspace khách, script tạo tenant `retailops-demo`, tài khoản riêng `owner` và giữ quota API.
SQLite persistent hiện có được import cùng membership, mã đăng nhập, order, audit và checkpoint; phiên đăng nhập cũ hết hiệu lực.

Lấy script từ image đã được CI/CD kiểm tra (không phụ thuộc link raw GitHub):

```bash
cd /opt/retailops
sudo python3 - <<'PY'
from pathlib import Path
import subprocess
image = next(x.split('=',1)[1] for x in Path('deployed.env').read_text().splitlines() if x.startswith('RETAILOPS_IMAGE='))
cid = subprocess.check_output(['docker','create','--network','none',image],text=True).strip()
try:
    subprocess.run(['docker','cp',cid+':/app/deploy/migrate-public-postgres.py','/opt/retailops/migrate-public-postgres.py'],check=True)
finally:
    subprocess.run(['docker','rm',cid],check=True)
PY
```

Sau đó chạy, thay hostname bằng hostname trỏ tới **Public IPv4 hiện tại** của EC2:

```bash
sudo python3 /opt/retailops/migrate-public-postgres.py --host retailops.YOUR-IP.sslip.io
```

Kết quả `POSTGRES_CUTOVER_OK`, sau đó kiểm tra HTTPS `/healthz` có `storage_backend: postgresql`.
Thư mục backup nằm ở `/opt/retailops/backups/postgres-cutover-*`; giữ nguyên cả backup và volume.
Nếu script rollback, không chạy lại mù quáng: kiểm tra target PostgreSQL đã có dữ liệu trước khi tiếp tục.

Guest chuyển sang persistent: lấy mã cá nhân **trên terminal riêng** bằng
`sudo cat /opt/retailops/artifacts/access/retailops-owner.code`. Không đưa mã vào Git/log/chat.
Mã này không phải inference token. Persistent import giữ mã cũ. Đăng xuất không xóa order.

EC2 stop/start có thể đổi Public IPv4 nếu chưa có địa chỉ cố định. Hostname sslip.io phải theo IP mới.

## 2. Bật pgvector cho PostgreSQL đã có trước 0.10

Nếu bước 1 vừa tạo PostgreSQL từ image 0.10, extension đã được cài; bỏ qua phần này.
Với volume PostgreSQL 16 hiện có: backup trước, chép `compose.postgres.yaml`,
`compose.rag.yaml` và `enable-pgvector.sql` từ image 0.10 vào `/opt/retailops`.
Dùng cùng project/volume `retailops-web`; không chạy `down --volumes`.

```bash
cd /opt/retailops
sudo docker compose --project-name retailops-web --env-file deployed.env --env-file public.env -f compose.public.yaml -f compose.postgres.yaml up -d --wait postgres
sudo docker compose --project-name retailops-web --env-file deployed.env --env-file public.env -f compose.public.yaml -f compose.postgres.yaml exec -T postgres psql -U postgres -d retailops < enable-pgvector.sql
```

Extension nằm trong schema `retailops_extensions` do admin sở hữu. Role ứng dụng chỉ có USAGE,
không được SUPERUSER/CREATEDB/CREATEROLE. Chuyển image vẫn giữ PostgreSQL major 16.

## 3. Chuẩn bị embedding và publish collection

Chép `compose.rag.yaml` từ image 0.10 vào `/opt/retailops` (script bước 1 cũng chép file này).
Chạy lần lượt; model tải bằng CPU, không cần Colab hoặc API key. Cần mạng tới Hugging Face ở bước prepare.
Tải thất bại để lại thư mục chưa có manifest: kiểm tra rồi chọn một thư mục mới; không ghi đè model đang dùng.

```bash
cd /opt/retailops
sudo docker compose --project-name retailops-web --env-file deployed.env --env-file public.env -f compose.public.yaml -f compose.postgres.yaml -f compose.rag.yaml run --rm --no-deps -e HF_HUB_OFFLINE=0 --entrypoint python web -m retailops knowledge prepare-model --directory /data/embedding-model
sudo docker compose --project-name retailops-web --env-file deployed.env --env-file public.env -f compose.public.yaml -f compose.postgres.yaml -f compose.rag.yaml run --rm --no-deps --entrypoint python web -m retailops knowledge publish --tenant retailops-demo --file /app/data/knowledge/demo.json
sudo docker compose --project-name retailops-web --env-file deployed.env --env-file public.env -f compose.public.yaml -f compose.postgres.yaml -f compose.rag.yaml run --rm --no-deps --entrypoint python web -m retailops knowledge search --tenant retailops-demo --query 'Chính sách đổi trả thế nào?'
```

Với tenant đã import, thay `retailops-demo` bằng tenant thật đã provision.
Giữ bản model + manifest cùng backup nếu cần khôi phục index đúng fingerprint.
Web RAG có giới hạn RAM 1 GiB; publication chạy ngoài web. Đây là cấu hình ban đầu, chưa được đo tải EC2.

## 4. Nối vào hội thoại

Custom Colab cần notebook mới `notebooks/colab_agent.ipynb` từ 0.10. Proxy giữ giao thức
`retailops-agent-v1` và bổ sung capability `knowledge-v1`/công cụ tra tài liệu.
Token hiện có trong Colab Secrets và EC2 giữ nguyên. Notebook không chạy PostgreSQL/embedding.
Proxy cũ vẫn dùng được khi RAG tắt; khi bật RAG, backend báo cần cập nhật proxy.
API OpenRouter sử dụng tool schema mới từ backend, không cần notebook.

```bash
cd /opt/retailops
sudo docker compose --project-name retailops-web --env-file deployed.env --env-file public.env -f compose.public.yaml -f compose.postgres.yaml -f compose.rag.yaml up -d --no-build --pull never --force-recreate --wait --wait-timeout 90 web
```

Nhớ giữ **cả ba file compose** khi cập nhật web RAG. Bỏ override RAG sẽ tắt truy xuất tài liệu.
Bỏ override PostgreSQL có thể khởi động web bằng cấu hình SQLite cũ; không làm vậy.

Thử `Chính sách đổi trả thế nào?`, `Phí giao hàng chính xác bao nhiêu?`, và `Kiểm tra đơn O-101`.
Kỳ vọng: chính sách có nguồn; số liệu còn thiếu được nói rõ; trạng thái đơn lấy từ `get_order`.
Tài liệu có câu yêu cầu hủy đơn không thể thay thế quyền customer, trạng thái/version và nút xác nhận.

## Backup/restore

Dump business/identity/knowledge/checkpoint bằng `pg_dump --no-owner --no-acl --exclude-schema=retailops_extensions`.
Trên DB đích, admin cài extension/schema với `enable-pgvector.sql` trước rồi restore dump bằng role ứng dụng.
Không restore một dump chứa lệnh cài extension bằng role ứng dụng hạn chế.
CI kiểm tra PostgreSQL thật, migration offline, quyền app và dump/restore; vector fixture kiểm tra hợp đồng,
không đại diện chất lượng embedding/model. Model weights thật cần kiểm tra prepare + search riêng.

## Còn lại

MCP/multi-agent chưa được triển khai ở bản này. LangGraph vẫn điều phối một agent có công cụ và
luồng xác nhận riêng. Chốt luồng PostgreSQL/RAG và dữ liệu trước khi thêm ranh giới agent mới.

Nguồn kỹ thuật: [pgvector](https://github.com/pgvector/pgvector),
[FastEmbed](https://qdrant.github.io/fastembed/),
[model multilingual MiniLM](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2).
