#!/usr/bin/env bash
set -euo pipefail
# Install once as /opt/retailops/deploy-runner.sh, root-owned and mode 0755.
# SSM executes this as root. No ngrok/model token is passed through SSM.
image_ref=${1:?Pass an ECR image pinned to its sha256 digest}
aws_region=${2:?Pass the AWS region}
deployment_dir=/opt/retailops
allowed_repo=$(cat "$deployment_dir/allowed-ecr-repository")
if [[ ! "$image_ref" =~ ^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]]; then
  echo 'Invalid ECR image reference' >&2
  exit 2
fi
if [[ "${image_ref%@*}" != "$allowed_repo" ]]; then
  echo 'Image repository is not the configured RetailOps repository' >&2
  exit 2
fi
if [[ ! "$aws_region" =~ ^[a-z]{2}(-[a-z]+)+-[0-9]$ ]]; then
  echo 'Invalid AWS region' >&2
  exit 2
fi
exec 9>"$deployment_dir/deploy.lock"
flock -n 9
registry_host=${image_ref%%/*}
aws ecr get-login-password --region "$aws_region" | docker login --username AWS --password-stdin "$registry_host"
docker pull "$image_ref"
docker run --rm --network none --entrypoint python "$image_ref" -m unittest discover -s tests -v
if [[ -f "$deployment_dir/deployed.env" ]]; then
  cp "$deployment_dir/deployed.env" "$deployment_dir/previous.env"
fi
umask 022
staging_path=$(mktemp "$deployment_dir/deployed.XXXXXX")
trap 'rm -f "$staging_path"' EXIT
printf 'RETAILOPS_IMAGE=%s\nRETAILOPS_DATA_DIR=/opt/retailops/artifacts\n' "$image_ref" > "$staging_path"
chmod 0644 "$staging_path"
mv "$staging_path" "$deployment_dir/deployed.env"
echo 'Baseline runner activated. Live evaluation is a separate attended operation.'
