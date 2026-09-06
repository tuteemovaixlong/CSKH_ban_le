"""CI entrypoint; requires short-lived AWS credentials, Docker and AWS CLI v2.

Activation installs a tested baseline image. It does not start a business API or
run live inference. The EC2 instance must already exist and be managed by SSM.
"""
import json
import os
import re
import shlex
import subprocess
import time


def run(*args, capture=True, input=None):
    return subprocess.run(args, input=input, text=True, check=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def value(key, pattern):
    val = os.environ.get(key, "")
    if not re.fullmatch(pattern, val):
        raise SystemExit(f"Missing or invalid {key}")
    return val


def main():
    region = value("AWS_REGION", r"[a-z]{2}(?:-[a-z]+)+-[0-9]")
    account = value("AWS_ACCOUNT_ID", r"[0-9]{12}")
    repo = value("ECR_REPOSITORY", r"[a-z0-9]+(?:[._/-][a-z0-9]+)*")
    instance = value("EC2_INSTANCE_ID", r"i-[a-f0-9]{8,17}")
    sha = value("GITHUB_SHA", r"[a-f0-9]{40}")
    run_id = value("GITHUB_RUN_ID", r"[0-9]+")
    attempt = value("GITHUB_RUN_ATTEMPT", r"[0-9]+")
    registry = f"{account}.dkr.ecr.{region}.amazonaws.com"
    tag = f"{sha}-{run_id}-{attempt}"
    image = f"{registry}/{repo}:{tag}"
    password = run("aws", "ecr", "get-login-password", "--region", region)
    run("docker", "login", "--username", "AWS", "--password-stdin", registry, input=password, capture=False)
    run("docker", "tag", "retailops:deploy", image, capture=False)
    run("docker", "push", image, capture=False)
    digest = run("aws", "ecr", "describe-images", "--region", region, "--repository-name", repo,
                 "--image-ids", f"imageTag={tag}", "--query", "imageDetails[0].imageDigest", "--output", "text").strip()
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise SystemExit("ECR returned an invalid image digest")
    pinned = f"{registry}/{repo}@{digest}"
    parameters = {"commands": [shlex.join(["/opt/retailops/deploy-runner.sh", pinned, region])],
                  "executionTimeout": ["600"]}
    command_id = run("aws", "ssm", "send-command", "--region", region,
                     "--instance-ids", instance, "--document-name", "AWS-RunShellScript",
                     "--parameters", json.dumps(parameters), "--timeout-seconds", "60",
                     "--query", "Command.CommandId", "--output", "text").strip()
    # Run Command has eventual consistency; poll for this specific invocation.
    deadline = time.monotonic() + 660
    while time.monotonic() < deadline:
        result = subprocess.run(["aws", "ssm", "get-command-invocation", "--region", region,
                                 "--command-id", command_id, "--instance-id", instance, "--output", "json"],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            if "InvocationDoesNotExist" not in result.stderr:
                raise SystemExit("Cannot query SSM invocation; inspect AWS permissions and command status")
        else:
            details = json.loads(result.stdout)
            status = details["Status"]
            if status == "Success":
                print(f"Activated baseline image: {pinned}")
                return
            if status not in ("Pending", "InProgress", "Delayed"):
                raise SystemExit(f"SSM activation ended with {status}; inspect the command in AWS")
        time.sleep(10)
    raise SystemExit("SSM polling deadline exceeded; inspect this invocation before retrying")


if __name__ == "__main__":
    main()
