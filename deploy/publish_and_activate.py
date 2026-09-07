"""CI deployment entrypoint; requires short-lived AWS credentials, Docker and AWS CLI v2.

The release image is tested, pushed by digest, activated on EC2, then rolled into the
public web service when that service is already configured. Baseline-only hosts remain
baseline-only. Live paid inference is never invoked by this deployment path.
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


def ssm_run(region, instance, command, execution_timeout=600):
    parameters = {"commands": [command], "executionTimeout": [str(execution_timeout)]}
    command_id = run("aws", "ssm", "send-command", "--region", region,
                     "--instance-ids", instance, "--document-name", "AWS-RunShellScript",
                     "--parameters", json.dumps(parameters), "--timeout-seconds", "60",
                     "--query", "Command.CommandId", "--output", "text").strip()
    deadline = time.monotonic() + execution_timeout + 60
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
                output = details.get("StandardOutputContent", "").strip()
                if output:
                    print(output)
                return
            if status not in ("Pending", "InProgress", "Delayed"):
                raise SystemExit(f"SSM deployment step ended with {status}; inspect command {command_id} in AWS")
        time.sleep(10)
    raise SystemExit(f"SSM polling deadline exceeded for command {command_id}; inspect the invocation before retrying")


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

    ssm_run(region, instance, shlex.join(["/opt/retailops/deploy-runner.sh", pinned, region]))
    print(f"Activated baseline image: {pinned}")

    # Install attended helpers from the exact tested release image. Only the public
    # web rollout runs automatically; database migration helpers remain operator-only.
    rollout = f"""
set -euo pipefail
cd /opt/retailops
image_ref={shlex.quote(pinned)}
container=$(docker create --network none "$image_ref")
staging=$(mktemp -d /opt/retailops/release-helpers.XXXXXX)
cleanup() {{ docker rm "$container" >/dev/null 2>&1 || true; rm -rf "$staging"; }}
trap cleanup EXIT
for helper in rollout-public-web.sh cutover-postgres.sh enable-pgvector.sh; do
  docker cp "$container:/app/deploy/$helper" "$staging/$helper"
  test -s "$staging/$helper"
  /bin/bash -n "$staging/$helper"
  install -o root -g root -m 0755 "$staging/$helper" "/opt/retailops/$helper"
done
docker cp "$container:/app/deploy/live-e2e.py" "$staging/live-e2e.py"
test -s "$staging/live-e2e.py"
python3 -m py_compile "$staging/live-e2e.py"
install -o root -g root -m 0755 "$staging/live-e2e.py" /opt/retailops/live-e2e.py
/opt/retailops/rollout-public-web.sh "$image_ref"
""".strip()
    ssm_run(region, instance, "/bin/bash -lc " + shlex.quote(rollout))
    print("Public web rollout checked for the activated image")

    # Every configured public release must pass a credential-safe live smoke through
    # Caddy and the real PostgreSQL-backed session/business path. This does not call a
    # model and therefore does not spend paid inference. A baseline-only host skips it.
    smoke = f"""
set -euo pipefail
if [[ -f /opt/retailops/public.env ]]; then
  python3 /opt/retailops/live-e2e.py --mode smoke --expected-image {shlex.quote(pinned)}
else
  echo LIVE_E2E_SMOKE_SKIPPED_PUBLIC_WEB_NOT_CONFIGURED
fi
""".strip()
    ssm_run(region, instance, "/bin/bash -lc " + shlex.quote(smoke), execution_timeout=300)
    print("Live smoke checked for the activated image")


if __name__ == "__main__":
    main()
