# The enclave image. Everything in here is measured by PCR0 (spec, section 5):
# change one line or one formula, rebuild, and the KMS key refuses the new image until PCR0 is updated.
# Build context: the src/ folder synced from S3 (payslip/ + enclave/), see build_enclave.sh.
FROM amazonlinux:2023

RUN dnf install -y python3 python3-cryptography && dnf clean all

WORKDIR /app

# AWS kmstool (attestation + KMS Decrypt), built from the pinned SDK release by build_enclave.sh
COPY enclave/kmstool_enclave_cli enclave/libnsm.so ./

# Our code: formulas, Mode A, envelope format, vsock framing, the enclave app
COPY payslip/payroll_rules.py payslip/reconcile.py payslip/envelope.py ./
COPY enclave/vsock_proto.py enclave/enclave_app.py ./

ENV LD_LIBRARY_PATH=/app \
    KMSTOOL=/app/kmstool_enclave_cli \
    PYTHONUNBUFFERED=1

CMD ["python3", "/app/enclave_app.py"]
