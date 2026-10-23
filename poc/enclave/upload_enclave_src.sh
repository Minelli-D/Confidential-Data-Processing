#!/bin/bash
# ON YOUR LAPTOP, before `terraform apply` on lab:  bash poc/enclave/upload_enclave_src.sh "$BUCKET"
# Uploads only what the enclave image and the parent need to s3://<bucket>/enclave/src/ (no tests, no data).
set -euo pipefail

BUCKET="${1:?usage: upload_enclave_src.sh <bucket>}"
REGION="${REGION:-eu-north-1}"
cd "$(dirname "$0")/.."   # poc/

aws s3 sync . "s3://$BUCKET/enclave/src/" --region "$REGION" --delete \
  --exclude "*" \
  --include "payslip/payroll_rules.py" --include "payslip/reconcile.py" --include "payslip/envelope.py" \
  --include "enclave/*" \
  --exclude "enclave/test_*" --exclude "*__pycache__*" \
  --exclude "enclave/kmstool_enclave_cli" --exclude "enclave/libnsm.so"

echo "uploaded. Check with: aws s3 ls s3://$BUCKET/enclave/src/ --recursive --region $REGION"
