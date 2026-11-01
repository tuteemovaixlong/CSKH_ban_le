#!/usr/bin/env python3
"""Retired legacy EC2 mutation helper (Phase R1 W2 — W2-D7).

This script is permanently retired and refuses to execute any file writes,
bind-mount code overlays, container recreations, or ad-hoc database DDL.
"""
import sys

RETIREMENT_GUIDANCE = """\
[BLOCKED] scripts/update_ec2.py đã ngừng sử dụng (Phase R1 W2 — W2-D7).
Không sử dụng script này để vá nóng mã nguồn hay sửa trực tiếp database trên EC2.

Hướng dẫn vận hành chuẩn:

1) Cập nhật endpoint suy luận (Colab / vLLM / OpenAI-compatible):
   - Chỉnh trực tiếp biến RETAILOPS_API_ENDPOINT (và RETAILOPS_API_MODEL nếu cần)
     trong /opt/retailops/api.env trên EC2 qua AWS SSM.
   - Tạo lại riêng container web từ release image đã phát hành:
     sudo docker compose --project-name retailops-web \\
       --env-file /opt/retailops/deployed.env \\
       --env-file /opt/retailops/public.env \\
       -f /opt/retailops/compose.public.yaml \\
       -f /opt/retailops/compose.postgres.yaml \\
       up -d --no-deps --no-build --pull never --force-recreate web

2) Phát hành mã nguồn hoặc cập nhật cấu hình public host/origin:
   - Phát hành qua workflow CI/CD chuẩn (deploy/publish_and_activate.py +
     deploy/rollout-public-web.sh), cập nhật /opt/retailops/public.env,
     /opt/retailops/admin.env và Caddyfile chính thức nếu đổi IP tĩnh/động.

3) Nâng cấp schema database có kiểm soát (theo runbook Phase R1):
   - Thực hiện preflight chỉ đọc, sao lưu pg_dump và kiểm chứng bản sao lưu trước.
   - Chạy lệnh migrate tường minh có xác nhận:
     python -m retailops identity migrate-v5 --confirm-preflight --confirm-backup
     python -m retailops database migrate-v5 --confirm-preflight --confirm-backup
"""


def main(argv=None) -> int:
    del argv
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.write(RETIREMENT_GUIDANCE)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
