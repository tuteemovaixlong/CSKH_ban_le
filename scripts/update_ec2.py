#!/usr/bin/env python3
"""Automated, robust deployment script for EC2 patch-mount deployment.
Executes cleanly on the EC2 host without any multi-line terminal pasting issues.
"""
import os
import shutil
import subprocess
from pathlib import Path


def main():
    repo_dir = Path(__file__).resolve().parents[1]
    patches_dir = Path("/opt/retailops/patches")
    compose_path = Path("/opt/retailops/compose.public.yaml")
    base_compose_path = repo_dir / "deploy" / "compose.public.yaml"

    print(f"[*] Updating EC2 patches from repository at: {repo_dir}")

    # 1. Clean and copy directories and files
    patches_dir.mkdir(parents=True, exist_ok=True)

    for folder in ["web", "retailops"]:
        dst = patches_dir / folder
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(repo_dir / folder, dst)
        print(f"  [+] Copied {folder} -> {dst}")

    for filename in ["retailops_providers.py", "agent_protocol.py"]:
        src = repo_dir / filename
        if src.exists():
            shutil.copy2(src, patches_dir / filename)
            print(f"  [+] Copied {filename} -> {patches_dir / filename}")

    # 2. Fix permissions so container user 10001 can read all files
    print("[*] Setting read/execute permissions (chmod -R a+rX)...")
    subprocess.run(["chmod", "-R", "a+rX", str(patches_dir)], check=True)

    # 3. Generate clean compose.public.yaml without any terminal paste artifacts
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

    compose_path.write_text("\n".join(output) + "\n", encoding="utf-8")
    print(f"  [+] Written {compose_path}")

    # 4. Restart containers
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
    print("\n[SUCCESS] Deployment complete! Run 'sudo docker ps' to verify healthy status.")


if __name__ == "__main__":
    main()
