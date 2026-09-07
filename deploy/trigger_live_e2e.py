#!/usr/bin/env python3
"""Trigger the installed live E2E runner on EC2 through SSM and stream only safe output."""
import argparse
import json
import os
import re
import subprocess
import time


def value(key, pattern):
    val = os.environ.get(key, "")
    if not re.fullmatch(pattern, val):
        raise SystemExit(f"Missing or invalid {key}")
    return val


def run(*args):
    return subprocess.run(args, text=True, check=True, stdout=subprocess.PIPE).stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("smoke", "full"), required=True)
    args = parser.parse_args()
    region = value("AWS_REGION", r"[a-z]{2}(?:-[a-z]+)+-[0-9]")
    instance = value("EC2_INSTANCE_ID", r"i-[a-f0-9]{8,17}")
    timeout = 1200 if args.mode == "full" else 300
    command = f"python3 /opt/retailops/live-e2e.py --mode {args.mode}"
    parameters = {"commands": [command], "executionTimeout": [str(timeout)]}
    command_id = run(
        "aws", "ssm", "send-command", "--region", region,
        "--instance-ids", instance, "--document-name", "AWS-RunShellScript",
        "--parameters", json.dumps(parameters), "--timeout-seconds", "60",
        "--query", "Command.CommandId", "--output", "text",
    ).strip()
    deadline = time.monotonic() + timeout + 60
    while time.monotonic() < deadline:
        result = subprocess.run([
            "aws", "ssm", "get-command-invocation", "--region", region,
            "--command-id", command_id, "--instance-id", instance, "--output", "json",
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            if "InvocationDoesNotExist" not in result.stderr:
                raise SystemExit(f"Cannot query SSM command {command_id}")
        else:
            details = json.loads(result.stdout)
            status = details["Status"]
            if status == "Success":
                output = details.get("StandardOutputContent", "").strip()
                if output:
                    print(output)
                return
            if status not in ("Pending", "InProgress", "Delayed"):
                raise SystemExit(f"Live E2E ended with {status}; inspect SSM command {command_id}")
        time.sleep(10)
    raise SystemExit(f"Live E2E timed out; inspect SSM command {command_id}")


if __name__ == "__main__":
    main()
