#!/usr/bin/env python3
"""Get or issue a fresh login code for RetailOps web interface on EC2.
Works for both synthetic-demo (invite token) and persistent-demo (personal credential).
"""
import os
import subprocess
from pathlib import Path


def main():
    public_env = Path("/opt/retailops/public.env")
    data_mode = "persistent-demo"
    invite_token = None

    if public_env.exists():
        for line in public_env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("RETAILOPS_DATA_MODE="):
                data_mode = line.split("=", 1)[1].strip()
            elif line.startswith("RETAILOPS_PUBLIC_INVITE_TOKEN="):
                invite_token = line.split("=", 1)[1].strip()

    print(f"[*] Che do RetailOps: {data_mode}")

    if data_mode == "synthetic-demo" and invite_token:
        print("\n" + "=" * 55)
        print("[SUCCESS] MA DANG NHAP (Guest / Invite Token):")
        print(invite_token)
        print("=" * 55 + "\n")
        return

    # In persistent-demo mode: issue a fresh credential via web container
    py_code = """
import os, secrets
from retailops.config import database_settings

backend, dsn = database_settings(os.environ)
if backend == 'postgresql':
    from retailops.identity.postgres import PostgresSessions
    sessions = PostgresSessions(dsn)
else:
    from retailops.identity.persistent import PersistentSessions
    sessions = PersistentSessions('/data/persistent')

try:
    sessions.provision_tenant('retailops-demo', 'RetailOps Demo', seed_demo=True)
except Exception:
    pass

try:
    mid = sessions.create_member('retailops-demo', 'mai-anh', 'Mai Anh', 'C-001', 'customer')
except Exception:
    if backend == 'postgresql':
        from retailops.storage.postgres import connection
        with connection(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM memberships WHERE tenant_id='retailops-demo' AND principal_id='mai-anh'")
                row = cur.fetchone()
                mid = row['id'] if isinstance(row, dict) else row[0]
    else:
        with sessions.control.connection() as db:
            row = db.execute("SELECT id FROM memberships WHERE tenant_id='retailops-demo' AND principal_id='mai-anh'").fetchone()
            mid = row['id']

token = secrets.token_urlsafe(32)
sessions.control.register_credential(mid, token)
print('\\n' + '=' * 55)
print('[SUCCESS] MA DANG NHAP MOI (Tai khoan Mai Anh - C-001):')
print(token)
print('=' * 55 + '\\n')
"""

    cmd = [
        "docker", "compose",
        "--project-name", "retailops-web",
        "--env-file", "deployed.env",
        "--env-file", "public.env",
        "-f", "compose.public.yaml",
        "exec", "-T", "web",
        "python", "-c", py_code
    ]
    try:
        subprocess.run(cmd, cwd="/opt/retailops", check=True)
    except Exception as e:
        if invite_token:
            print("\n" + "=" * 55)
            print("[FALLBACK] MA DANG NHAP (Invite Token tu public.env):")
            print(invite_token)
            print("=" * 55 + "\n")
        else:
            print(f"[!] Loi cap ma dang nhap: {e}")


if __name__ == "__main__":
    main()
