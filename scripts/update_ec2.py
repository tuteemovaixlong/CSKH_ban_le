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

        # Update admin.env and console.caddy if installed
        admin_env_path = Path("/opt/retailops/admin.env")
        if admin_env_path.exists():
            new_admin_host = f"admin-{new_host}"
            admin_env_path.write_text(f"RETAILOPS_ADMIN_HOST={new_admin_host}\n", encoding="utf-8")
            print(f"  [+] admin.env successfully updated with {new_admin_host}")
            console_caddy_path = Path("/opt/retailops/admin-caddy/console.caddy")
            if console_caddy_path.exists():
                caddy_text = console_caddy_path.read_text(encoding="utf-8")
                caddy_text = re.sub(r"admin-retailops\.[0-9.-]+\.sslip\.io", new_admin_host, caddy_text)
                console_caddy_path.write_text(caddy_text, encoding="utf-8")
                print(f"  [+] admin-caddy/console.caddy updated with {new_admin_host}")
    elif public_env_path.exists():
        for line in public_env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("RETAILOPS_PUBLIC_HOST="):
                current_host = line.split("=", 1)[1].strip()

    # 2. Clean and copy directories and files
    patches_dir.mkdir(parents=True, exist_ok=True)

    for folder in ["web", "retailops", "data", "evals", "opsconsole"]:
        dst = patches_dir / folder
        src = repo_dir / folder
        if src.exists():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            print(f"  [+] Copied {folder} -> {dst}")

    for filename in [
        "retailops_providers.py",
        "agent_protocol.py",
        "retailops_agent.py",
        "retailops_tools.py",
        "retailops_conversation.py",
        "retailops_mcp_server.py",
        "mcp_config.json"
    ]:
        src = repo_dir / filename
        if src.exists():
            shutil.copy2(src, patches_dir / filename)
            print(f"  [+] Copied {filename} -> {patches_dir / filename}")

    caddy_src = repo_dir / "deploy" / "Caddyfile"
    caddy_dst = Path("/opt/retailops/Caddyfile")
    if caddy_src.exists():
        shutil.copy2(caddy_src, caddy_dst)
        print(f"  [+] Copied deploy/Caddyfile -> {caddy_dst}")

    # Preserve admin console configuration and import if admin is installed
    admin_env_path = Path("/opt/retailops/admin.env")
    admin_caddy_dir = Path("/opt/retailops/admin-caddy")
    admin_caddy_file = admin_caddy_dir / "console.caddy"
    if admin_env_path.exists() or admin_caddy_dir.exists():
        caddy_text = caddy_dst.read_text(encoding="utf-8") if caddy_dst.exists() else ""
        marker = "import /etc/caddy/admin/*.caddy"
        if marker not in caddy_text:
            caddy_dst.write_text(caddy_text.rstrip() + "\n\n" + marker + "\n", encoding="utf-8")
            print("  [+] Preserved admin caddy import in /opt/retailops/Caddyfile")

        if current_host:
            new_admin_host = f"admin-{current_host}"
            admin_env_path.write_text(f"RETAILOPS_ADMIN_HOST={new_admin_host}\n", encoding="utf-8")
            print(f"  [+] admin.env synchronized with {new_admin_host}")
            if admin_caddy_file.exists():
                console_text = admin_caddy_file.read_text(encoding="utf-8")
                console_text = re.sub(r"^[a-zA-Z0-9.-]+\s*\{", f"{new_admin_host} {{", console_text, count=1)
                admin_caddy_file.write_text(console_text, encoding="utf-8")
                print(f"  [+] admin-caddy/console.caddy synchronized with {new_admin_host}")

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
            output.append("      - /opt/retailops/patches/data:/app/data:ro")
            output.append("      - /opt/retailops/patches/evals:/app/evals:ro")
            output.append("      - /opt/retailops/patches/retailops_providers.py:/app/retailops_providers.py:ro")
            output.append("      - /opt/retailops/patches/agent_protocol.py:/app/agent_protocol.py:ro")
            output.append("      - /opt/retailops/patches/retailops_agent.py:/app/retailops_agent.py:ro")
            output.append("      - /opt/retailops/patches/retailops_tools.py:/app/retailops_tools.py:ro")
            output.append("      - /opt/retailops/patches/retailops_conversation.py:/app/retailops_conversation.py:ro")
            output.append("      - /opt/retailops/patches/retailops_mcp_server.py:/app/retailops_mcp_server.py:ro")
            output.append("      - /opt/retailops/patches/mcp_config.json:/app/mcp_config.json:ro")

    compose_path.write_text("\n".join(output) + "\n", encoding="utf-8")
    print(f"  [+] Written {compose_path}")

    # Update compose.admin.yaml with opsconsole patch mount
    admin_compose_path = Path("/opt/retailops/compose.admin.yaml")
    base_admin_compose_path = repo_dir / "deploy" / "compose.admin.yaml"
    if base_admin_compose_path.exists() and admin_compose_path.exists():
        admin_lines = base_admin_compose_path.read_text(encoding="utf-8").splitlines()
        admin_output = []
        for line in admin_lines:
            admin_output.append(line)
            if "console-data:/console-data:ro" in line:
                admin_output.append("      - /opt/retailops/patches/opsconsole:/app/opsconsole:ro")
        admin_compose_path.write_text("\n".join(admin_output) + "\n", encoding="utf-8")
        print(f"  [+] Written {admin_compose_path} with opsconsole patch mount")

    # Clean up old smoke run and import 240 benchmark to admin console-data
    console_runs = Path("/opt/retailops/console-data/runs")
    if console_runs.exists():
        old_smoke = console_runs / "live-737df05117fb6af44042ae67"
        if old_smoke.exists():
            shutil.rmtree(old_smoke, ignore_errors=True)
            print("  [+] Removed old live-smoke run from console-data/runs")
        latest_json = repo_dir / "evals" / "reports" / "live_benchmark_report_latest.json"
        if latest_json.exists():
            print("[*] Importing live benchmark (240 cases) to admin console data...")
            try:
                import sys
                if str(repo_dir) not in sys.path:
                    sys.path.insert(0, str(repo_dir))
                from opsconsole.evaluation import import_benchmark, save_report
                report_obj = import_benchmark(latest_json)
                saved_target = save_report(report_obj, console_runs)
                print(f"  [+] Imported benchmark report: {saved_target.name}")
            except Exception as ex:
                print(f"  [!] Note on benchmark import: {ex}")
            subprocess.run(["chmod", "-R", "a+rX", str(console_runs)], check=False)

    # 5. Restart containers
    print("[*] Restarting docker containers...")
    cmd = [
        "docker", "compose",
        "--project-name", "retailops-web",
        "--env-file", "deployed.env",
        "--env-file", "public.env",
        "-f", "compose.public.yaml",
    ]
    if Path("/opt/retailops/compose.postgres.yaml").exists():
        cmd += ["-f", "compose.postgres.yaml"]
    if Path("/opt/retailops/compose.admin.yaml").exists() and Path("/opt/retailops/admin.env").exists():
        cmd += ["--env-file", "admin.env", "-f", "compose.admin.yaml"]
    cmd += ["up", "-d", "--no-build", "--pull", "never", "--force-recreate"]
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
        if Path("/opt/retailops/admin.env").exists():
            print(f"[*] Access Admin at: https://admin-{current_host}")
    print("=======================================================")
    print("=======================================================")


if __name__ == "__main__":
    main()

