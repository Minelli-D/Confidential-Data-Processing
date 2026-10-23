#!/bin/bash
# FIRST SESSION ONLY, on the EC2 instance (as root):  sudo bash /opt/poc/src/enclave/build_enclave.sh
# Builds the enclave image (EIF), prints PCR0, stores the image + PCRs in S3 enclave/ (spec 7.2, step 6).
# Later sessions reuse the stored image, so PCR0 never changes (decision AWS-7).
set -euo pipefail

# BUCKET and REGION come from /opt/poc/poc.env (written by the lab startup script)
# shellcheck source=/dev/null
[ -f /opt/poc/poc.env ] && . /opt/poc/poc.env
BUCKET="${1:-${BUCKET:?BUCKET not set: pass it as the first argument}}"
REGION="${REGION:-eu-north-1}"
DIR=/opt/poc

# kmstool comes from the AWS Nitro Enclaves SDK, pinned: a moving branch would change PCR0 on rebuild
SDK_TAG=v0.4.5
SDK_COMMIT=cd61b6187c8b20867ba4368d1ae62c5790c0269a

mkdir -p "$DIR" && cd "$DIR"
echo "== 1/5 source code from s3://$BUCKET/enclave/src/"
aws s3 sync "s3://$BUCKET/enclave/src/" "$DIR/src/" --region "$REGION" --delete

echo "== 2/5 kmstool from aws-nitro-enclaves-sdk-c $SDK_TAG"
rm -rf "$DIR/sdk"
git clone --quiet --depth 1 --branch "$SDK_TAG" https://github.com/aws/aws-nitro-enclaves-sdk-c.git "$DIR/sdk"
if [ "$(git -C "$DIR/sdk" rev-parse HEAD)" != "$SDK_COMMIT" ]; then
  echo "refused: $SDK_TAG does not point to the pinned commit $SDK_COMMIT" >&2
  exit 1
fi
(cd "$DIR/sdk/bin/kmstool-enclave-cli" && ./build.sh)
cp "$DIR/sdk/bin/kmstool-enclave-cli/kmstool_enclave_cli" "$DIR/sdk/bin/kmstool-enclave-cli/libnsm.so" "$DIR/src/enclave/"

echo "== 3/5 Docker image payslip-enclave:v1"
docker build -f "$DIR/src/enclave/Dockerfile" -t payslip-enclave:v1 "$DIR/src/"

echo "== 4/5 enclave image (EIF) + measurements"
nitro-cli build-enclave --docker-uri payslip-enclave:v1 --output-file "$DIR/payslip-enclave.eif" > "$DIR/pcrs.json"
cat "$DIR/pcrs.json"

echo "== 5/5 store image + PCRs in s3://$BUCKET/enclave/"
aws s3 cp "$DIR/payslip-enclave.eif" "s3://$BUCKET/enclave/payslip-enclave.eif" --region "$REGION"
aws s3 cp "$DIR/pcrs.json" "s3://$BUCKET/enclave/pcrs.json" --region "$REGION"

PCR0=$(jq -r '.Measurements.PCR0' "$DIR/pcrs.json")
echo
echo "PCR0=$PCR0"
echo "Next, on your laptop:  terraform -chdir=infra/base apply -var enclave_pcr0=$PCR0"
