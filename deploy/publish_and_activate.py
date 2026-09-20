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
    transient_worker_errors = (
        "document process failed unexpectedly",
        "ipc messaging received timeout signal",
    )

    # SSM Agent occasionally loses its document worker IPC channel even though the
    # instance itself is healthy. Retry that specific infrastructure failure once.
    # The deployment commands are intentionally idempotent, while genuine script
    # failures still fail immediately with their original stdout/stderr.
    for attempt in range(1, 3):
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
                    stdout_content = details.get("StandardOutputContent", "").strip()
                    stderr_content = details.get("StandardErrorContent", "").strip()
                    combined = f"{stdout_content}\n{stderr_content}".lower()
                    if stdout_content:
                        print(f"=== SSM STDOUT ({status}) ===\n{stdout_content}")
                    if stderr_content:
                        print(f"=== SSM STDERR ({status}) ===\n{stderr_content}")
                    response_code = details.get("ResponseCode")
                    status_details = details.get("StatusDetails", "")
                    # A RunShellScript command that reaches the shell always emits
                    # something in our deployment paths (the preflight starts with echo).
                    # Empty stdout+stderr therefore means the SSM worker/plugin failed
                    # before the remote shell could actually execute, regardless of the
                    # agent-specific response code used by that SSM Agent version.
                    failed_before_shell = (
                        status == "Failed"
                        and not stdout_content
                        and not stderr_content
                    )
                    is_transient_worker_failure = (
                        status == "Failed"
                        and (
                            any(marker in combined for marker in transient_worker_errors)
                            or failed_before_shell
                        )
                    )
                    if is_transient_worker_failure and attempt == 1:
                        print(
                            f"Transient SSM worker failure for command {command_id} "
                            f"(response_code={response_code}, status_details={status_details!r}); "
                            "retrying once in 20 seconds"
                        )
                        time.sleep(20)
                        break
                    if failed_before_shell:
                        raise SystemExit(
                            "SSM failed before the remote shell started. On this host the previous "
                            "deployment also reported root-disk exhaustion; free root disk space or "
                            "expand the root volume, then retry. "
                            f"Command={command_id} response_code={response_code} "
                            f"status_details={status_details!r}"
                        )
                    raise SystemExit(
                        f"SSM deployment step ended with {status}; inspect command {command_id} in AWS"
                    )
            time.sleep(10)
        else:
            raise SystemExit(
                f"SSM polling deadline exceeded for command {command_id}; inspect the invocation before retrying"
            )


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

    # Fail fast before publishing another release when the target host is unhealthy.
    # The previous incident filled the root filesystem with Docker/containerd data,
    # which can also prevent SSM from starting its document worker at all.
    preflight = """
set -euo pipefail
echo "=== EC2 DEPLOY PREFLIGHT ==="
df -h / || true
docker system df || true
journalctl --vacuum-size=128M >/dev/null 2>&1 || true
docker image prune -af
docker builder prune -af || true
echo "=== EC2 DISK AFTER PREFLIGHT CLEANUP ==="
df -h / || true
available_kb=$(df -Pk / | awk 'NR==2 {print $4}')
if [[ -z "$available_kb" || "$available_kb" -lt 1048576 ]]; then
  echo "EC2_ROOT_DISK_LOW: less than 1 GiB free after safe cleanup" >&2
  exit 75
fi
""".strip()
    ssm_run(region, instance, "/bin/bash -lc " + shlex.quote(preflight), execution_timeout=180)

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
docker cp "$container:/app/deploy/admin-console.py" "$staging/admin-console.py"
python3 -m py_compile "$staging/admin-console.py"
install -o root -g root -m 0755 "$staging/admin-console.py" /opt/retailops/admin-console.py
if ! /opt/retailops/rollout-public-web.sh "$image_ref"; then
  echo "=== DOCKER PS ==="
  docker ps -a
  echo "=== WEB CONTAINER LOGS ==="
  docker logs --tail 80 retailops-web-web-1 || true
  echo "=== POSTGRES CONTAINER LOGS ==="
  docker logs --tail 40 retailops-web-postgres-1 || true
  exit 1
fi
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

    # Never enable an admin origin implicitly. An attended first install provisions
    # the separate credential; subsequent releases refresh the existing console.
    admin = f"""
set -euo pipefail
if [[ -f /opt/retailops/admin.env ]]; then
  python3 /opt/retailops/admin-console.py install --image {shlex.quote(pinned)} --commit {shlex.quote(sha)}
  python3 /opt/retailops/live-e2e.py --mode smoke --expected-image {shlex.quote(pinned)}
else
  echo ADMIN_CONSOLE_NOT_CONFIGURED
fi
""".strip()
    ssm_run(region, instance, "/bin/bash -lc " + shlex.quote(admin), execution_timeout=600)

    # The previous web image becomes unused only after a successful rollout. Prune it
    # here so each deploy does not permanently consume another copy of large layers.
    post_cleanup = """
set -euo pipefail
docker image prune -af
docker builder prune -af || true
journalctl --vacuum-size=128M >/dev/null 2>&1 || true
echo "=== EC2 DISK AFTER RELEASE CLEANUP ==="
df -h / || true
""".strip()
    ssm_run(region, instance, "/bin/bash -lc " + shlex.quote(post_cleanup), execution_timeout=180)


if __name__ == "__main__":
    main()
