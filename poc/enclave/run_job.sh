#!/bin/bash
# EVERY SESSION, on the EC2 instance (as root):  sudo bash /opt/poc/src/enclave/run_job.sh
# Starts vsock-proxy (KMS) and the enclave, runs Mode A, uploads the report, then stops both (spec 7.3).
# Add --debug-mode only to check that the app starts: its PCR0 is all zeros, so KMS will refuse it.
set -euo pipefail

# shellcheck source=/dev/null
[ -f /opt/poc/poc.env ] && . /opt/poc/poc.env
BUCKET="${BUCKET:?BUCKET not set: check /opt/poc/poc.env}"
REGION="${REGION:-eu-north-1}"
DEBUG_FLAG="${1:-}"
DIR=/opt/poc
EIF="$DIR/payslip-enclave.eif"
CPU_COUNT="${ENCLAVE_CPU_COUNT:-2}"
MEMORY_MIB="${ENCLAVE_MEMORY_MIB:-4096}"

echo "== source code and enclave image from S3"
aws s3 sync "s3://$BUCKET/enclave/src/" "$DIR/src/" --region "$REGION" --delete
[ -f "$EIF" ] || aws s3 cp "s3://$BUCKET/enclave/payslip-enclave.eif" "$EIF" --region "$REGION"

echo "== vsock-proxy: the enclave's only way to reach KMS (allow-listed host only)"
vsock-proxy 8000 "kms.$REGION.amazonaws.com" 443 --config /etc/nitro_enclaves/vsock-proxy.yaml &
PROXY_PID=$!

cleanup() {
  nitro-cli terminate-enclave --all > /dev/null 2>&1 || true   # the enclave's memory is wiped here
  kill "$PROXY_PID" 2> /dev/null || true
}
trap cleanup EXIT

echo "== start the enclave ($CPU_COUNT vCPU, $MEMORY_MIB MiB) $DEBUG_FLAG"
# shellcheck disable=SC2086  # DEBUG_FLAG is empty or exactly one flag
nitro-cli run-enclave --eif-path "$EIF" --cpu-count "$CPU_COUNT" --memory "$MEMORY_MIB" $DEBUG_FLAG
nitro-cli describe-enclaves

echo "== run the job"
python3 "$DIR/src/enclave/run_job.py" --bucket "$BUCKET" --region "$REGION" --out-dir "$DIR/reports"
