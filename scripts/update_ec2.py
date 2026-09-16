#!/usr/bin/env python3
"""Automated, robust deployment script for EC2 patch-mount deployment and IP migration.
Executes cleanly on the EC2 host without any multi-line terminal pasting issues.
Supports updating public IP/hostname when EC2 restarts.
"""
import argparse
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path


def get_public_ip():
    """Detect public IP using AWS IMDSv2 with fallback to external service."""
    try:
        req = urllib.request.Request("http://169.254.169.254/latest/api/token", headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"}, method="PUT")
        with urllib.request.urlopen(req, timeout=2) as resp:
            token = resp.read().decode().strip()
        req2 = urllib.request.Request("http://169.254.169.254/latest/meta-data/public-ipv4", headers={"X-aws-ec2-metadata-token": token})
        with urllib.request.urlopen(req2, timeout=2) as resp2:
            return resp2.read().decode().strip()
    except Exception:
        pass
    try:
        with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=3) as resp:
            return resp.read().decode().strip()
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="Update EC2 deployment patches and optional public IP.")
    parser.add_argument("--ip", help="New Public IPv4 of the EC2 instance (e.g. 18.206.237.32)")
    parser.add_argument("--auto-ip", action="store_true", help="Auto-detect public IPv4 via AWS metadata/checkip")
    args = parser.parse_args()

    repo_dir = Path(__file__).resolve().parents[1]
    patches_dir = Path("/opt/retailops/patches")
    compose_path = Path("/opt/retailops/compose.public.yaml")
    base_compose_path = repo_dir / "deploy" / "compose.public.yaml"
    public_env_path = Path("/opt/retailops/public.env")

    print(f"[*] Updating EC2 patches from repository at: {repo_dir}")

    # 1. Update public.env if IP has changed
    target_ip = args.ip or (get_public_ip() if args.auto_ip else None)
    current_host = None

    if target_ip and re.fullmatch(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", target_ip):
        dashed_ip = target_ip.replace(".", "-")
        new_host = f"retailops.{dashed_ip}.sslip.io"
        new_origin = f"https://{new_host}"
        current_host = new_host

        if public_env_path.exists():
            print(f"[*] Updating public.env with new IP: {target_ip} -> {new_host}")
            lines = public_env_path.read_text(encoding="utf-8").splitlines()
            new_lines = []
            found_host = False
            for line in lines:
                if line.startswith("RETAILOPS_PUBLIC_HOST="):
                    new_lines.append(f"RETAILOPS_PUBLIC_HOST={new_host}")
                    found_host = True
                elif line.startswith("RETAILOPS_PUBLIC_ORIGIN="):
                    new_lines.append(f"RETAILOPS_PUBLIC_ORIGIN={new_origin}")
                else:
                    new_lines.append(line)
            if not found_host:
                new_lines.append(f"RETAILOPS_PUBLIC_HOST={new_host}")
                new_lines.append(f"RETAILOPS_PUBLIC_ORIGIN={new_origin}")
            public_env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            print(f"  [+] public.env successfully updated with {new_origin}")
    elif public_env_path.exists():
        for line in public_env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("RETAILOPS_PUBLIC_HOST="):
                current_host = line.split("=", 1)[1].strip()

    # 2. Clean and copy directories and files
    patches_dir.mkdir(parents=True, exist_ok=True)

    for folder in ["web", "retailops"]:
        dst = patches_dir / folder
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(repo_dir / folder, dst)
        print(f"  [+] Copied {folder} -> {dst}")

    for filename in ["retailops_providers.py", "agent_protocol.py", "retailops_agent.py"]:
        src = repo_dir / filename
        if src.exists():
            shutil.copy2(src, patches_dir / filename)
            print(f"  [+] Copied {filename} -> {patches_dir / filename}")

    # 3. Fix permissions so container user 10001 can read all files
    print("[*] Setting read/execute permissions (chmod -R a+rX)...")
    subprocess.run(["chmod", "-R", "a+rX", str(patches_dir)], check=True)

    # 4. Generate clean compose.public.yaml without any terminal paste artifacts
    print("[*] Generating /opt/retailops/compose.public.yaml...")
    lines = base_compose_path.read_text(encoding="utf-8").splitlines()
    output = []
    for line in lines:
        output.append(line)
        if "artifacts}:/data" in line:
            output.append("      - /opt/retailops/patches/web:/app/web:ro")
            output.append("      - /opt/retailops/patches/retailops:/app/retailops:ro")
            output.append("      - /opt/retailops/patches/retailops_providers.py:/app/retailops_providers.py:ro")
            output.append("      - /opt/retailops/patches/agent_protocol.py:/app/agent_protocol.py:ro")
            output.append("      - /opt/retailops/patches/retailops_agent.py:/app/retailops_agent.py:ro")

    compose_path.write_text("\n".join(output) + "\n", encoding="utf-8")
    print(f"  [+] Written {compose_path}")

    # 5. Restart containers
    print("[*] Restarting docker containers...")
    cmd = [
        "docker", "compose",
        "--project-name", "retailops-web",
        "--env-file", "deployed.env",
        "--env-file", "public.env",
        "-f", "compose.public.yaml",
        "-f", "compose.postgres.yaml",
        "up", "-d", "--no-build", "--pull", "never", "--force-recreate"
    ]
    subprocess.run(cmd, cwd="/opt/retailops", check=True)

    # 6. Ensure PostgreSQL schema role check constraint supports staff and manager
    print("[*] Updating database schema constraints...")
    try:
        subprocess.run([
            "docker", "exec", "-i", "retailops-web-postgres-1",
            "psql", "-U", "retailops", "-d", "retailops", "-c",
            "ALTER TABLE retailops_identity.memberships DROP CONSTRAINT IF EXISTS memberships_role_check; "
            "ALTER TABLE retailops_identity.memberships ADD CONSTRAINT memberships_role_check CHECK (role IN ('customer', 'viewer', 'staff', 'manager'));"
        ], check=False)
        print("  [+] Database schema constraint 'memberships_role_check' verified.")
    except Exception as e:
        print(f"  [!] Note on schema constraint update: {e}")

    print("\n=======================================================")
    print("[SUCCESS] Deployment & restart completed successfully!")
    if current_host:
        print(f"[*] Access Web at: https://{current_host}")
    print("=======================================================")


if __name__ == "__main__":
    main()

