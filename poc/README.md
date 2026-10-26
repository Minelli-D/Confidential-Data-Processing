# Confidential Data Processing · POC

Prove on real AWS hardware that sensitive data (synthetic payslips) can be decrypted **only inside a verified Nitro Enclave**, processed there, and leave nothing usable behind.

**Status:** the first run on AWS worked: the job ran inside a real Nitro Enclave, and everything was destroyed the same afternoon. That run didn't record the status line, tests B1/B2 or the score, so the next run will capture them as the formal proof. The whole story is in `confidential-poc-handbook.docx`.

## Where things are

| Path | What |
|---|---|
| `poc/payslip/` | the formulas (`payroll_rules.py`), Mode A (`reconcile.py`), the dataset generator, the envelope format (`envelope.py`), the encryption script (`encrypt_input.py`), the scoring script (`score_report.py`), 47 tests |
| `poc/enclave/` | the enclave app (`enclave_app.py`), vsock framing, the parent runner (`run_job.py` + `run_job.sh`), `Dockerfile` + `build_enclave.sh`, `upload_enclave_src.sh`, 23 tests |
| `poc/procedures/` | step-by-step procedures: **base phase** and **lab phase** |
| `data/` | synthetic dataset `payslips-2026-H1.json` and `answer-key-2026-H1.json` (the answer key never goes to S3 or the enclave) |
| `infra/base/` | Terraform **kept** between sessions: KMS key, S3 bucket, IAM role, budget alert |
| `infra/lab/` | Terraform **per session**: VPC, security group, EC2 instance with enclaves |
| `schemas/` | diagrams (SVG source + PNG) |
| `tools/docgen/` | the scripts that regenerate every .docx and diagram (kept outside the published repository) |
| `*.docx` | the documents (see [Documents](#documents)) |

## Decisions

All decisions were taken. TASK-01 and TASK-02, the labels you'll see on the documents, are the two parts of the work: the data and formulas, then the AWS deployment.

### Data and formulas (TASK-01)

| ID | Decision | Why |
|---|---|---|
| DATA-1 | **Synthetic data only**: 100 employees, January–June 2026, EUR | no real person; safe to test anywhere |
| DATA-2 | **Italian payroll rules, simplified** (not exact to any CCNL) | realistic but quick; POC only |
| DATA-3 | Four payslip items: **overtime, bank holidays, sick days, termination** | the owner asked for 3–4 items |
| DATA-4 | Reconciliation: **Mode A** (check the issued payslips) first, then **Mode B** (compute the next month), with the same formulas | Mode A can be tested; Mode B reuses the same formulas |
| DATA-5 | **~5% planted errors** (29 of 580 payslips) plus a separate **answer key** | proves the check finds exactly the errors: none missed, none extra |
| DATA-6 | Field names **proposed by Claude** (data dictionary), reviewed afterwards by the owner | unblocks the JSON |
| DATA-7 | **Formulas as code** inside the enclave image, so PCR0 measures them. The dataset declares `rules_version`, and the code refuses a mismatch | strictest option: any formula change becomes a reviewed key-policy change |

### AWS deployment (TASK-02)

| ID | Decision | Why |
|---|---|---|
| AWS-1 | Region **eu-north-1 (Stockholm)** | the owner's choice |
| AWS-2 | Terraform split: **base** (kept, ~$1/month) + **lab** (per session, destroyed) | pay only while working |
| AWS-3 | **One KMS key**, created once, never rotated, protected from destroy | each rotation adds $1/month; the data stays decryptable across sessions |
| AWS-4 | **Tier 1 only**: one EC2 instance, **no EKS** | EKS doesn't replace EC2, it only adds orchestration; Tier 1 proves the hard part |
| AWS-5 | ~~Spot~~ | replaced by AWS-10 |
| AWS-6 | **Public subnet, 0 inbound rules**, outbound HTTPS (+ port 80 since AWS-12), access through **SSM**, IMDSv2 | the first session needs internet to build; the key policy, not the network, protects the data |
| AWS-7 | Ready-made parts: **Amazon Linux 2023, nitro-cli + vsock-proxy, kmstool-enclave-cli**. Docker is used only to build the enclave image once; the image is stored in S3 | Fargate and Lambda can't run enclaves; less of our own code in the trusted part |
| AWS-8 | **No output encryption in the POC**: the report goes to the private bucket in clear (SSE-S3 at rest) | synthetic data; the input stays fully protected. Real data → guide section 2.5 |
| AWS-9 | **m6i.xlarge**; the enclave gets **2 vCPU + 4 GiB** | twice the memory of c6i; the enclave image lives in RAM |
| AWS-10 | **On-Demand** (`use_spot = false`) | no capacity surprises; ~$0.65 per 3-hour session |
| AWS-11 | **Terraform runs as the account root user** (known deviation) | the owner's choice for the POC. The key-policy principal becomes `…:root`: key admin and encrypt are delegated to IAM in the account, but **Decrypt is still only for the attested enclave** |
| AWS-12 | **Outbound port 80** added to the lab security group (session 1) | the kmstool build's Amazon Linux 2 container fetches its yum mirror list over HTTP. Packages are GPG-signed, so integrity doesn't depend on TLS. Still zero inbound |

### Rules that follow from the decisions

**The key policy:**

| Who | May do | Condition | May NOT do |
|---|---|---|---|
| You (the identity that runs Terraform) | manage the key | none | **Decrypt** |
| You as data owner | GenerateDataKey, Encrypt | none | **Decrypt** |
| EC2 instance role | **Decrypt only** | **attestation with PCR0 = our image** | everything else |
| Anyone else, including any IAM policy | nothing | | |

The design has no "account root" statement, so that only the key policy decides. **As deployed (AWS-11)**, Terraform ran as the root user, so the principal of rows 1–2 is `…:root`: any IAM admin in the account can also manage the key and encrypt. Nobody can Decrypt except the attested enclave. **Never delete the identity that runs Terraform.**

**Two layers of encryption on the way into S3:**
- **Layer 1, the envelope:** the payslip JSON is encrypted on the laptop with a KMS data key (AES-256-GCM). Only the attested enclave can unlock it.
- **Layer 2, at rest:** S3 encrypts the object again (SSE-S3).

**Who does what:** S3 is the post office, the parent instance is the courier (it only ever carries ciphertext), and the enclave is the only reader.

**PCR0 is pinned in two steps:**
- First `apply` of base without PCR0.
- Build the image, then `apply` again with `enclave_pcr0`.
- Terraform refuses a PCR0 of all zeros (debug mode).

**Three cost safety nets:**
1. `terraform destroy` on lab after every session.
2. A **self-destruct timer**: the instance terminates itself 4 hours after boot.
3. A **$5/month budget alert**.

### Implementation choices (lab phase)

| ID | Choice | Why |
|---|---|---|
| IMPL-1 | kmstool built from the AWS Nitro Enclaves SDK **v0.4.5**, commit `cd61b618…` checked by `build_enclave.sh` | a moving branch would change PCR0 on rebuild |
| IMPL-2 | The enclave image: **Amazon Linux 2023 + Python 3.9 + python3-cryptography** + kmstool + our code | verified locally: the image builds and the enclave logic runs with no network |
| IMPL-3 | Parent ↔ enclave: **vsock port 5000**, 8-byte length + JSON, max 64 MB; KMS through **vsock-proxy port 8000** | simple framing, tested; the enclave's only way to KMS is allow-listed |
| IMPL-4 | The status line has **no personal data** (counts, rules version, report hash); errors return only type + short message, credentials redacted | the parent is untrusted |
| IMPL-5 | The parent uploads the report **only if its SHA-256 matches** the hash in the status line | catches a damaged or altered report |
| IMPL-6 | The lab startup script writes **`/opt/poc/poc.env`** (bucket, region, enclave size) and pre-loads the source from S3 | the scripts on the instance need no arguments |
| IMPL-7 | PCR0 is kept in **`infra/base/pcr0.auto.tfvars`** (git-ignored) | a later `apply` on base can't silently drop the enclave statement |
| IMPL-8 | **PCR0 is never copied by hand**: read it from `pcrs.json` in S3 and check it has 96 characters | in session 1 a hand-copied PCR0 lost one character; the guard refused it |

## Success tests

| Test | Pass when |
|---|---|
| **A** | the enclave decrypts the payslips, runs Mode A, and the report scores **29 matched, 0 missed, 0 unexpected** |
| **B1** | the instance's own Decrypt, outside the enclave → **AccessDenied** |
| **B2** | your own Decrypt from the laptop → **AccessDenied** |
| **C** (POC) | the report is stored in the private bucket (in clear, AWS-8) |
| **D** | after `terraform destroy`, only the base setup remains |

## POC simplifications (deliberately not production)

| Simplification | Production version |
|---|---|
| Synthetic data, simplified payroll rules (flat IRPEF, simplified sick pay and TFR) | real data, exact rules for the CCNL |
| Report in clear (AWS-8) | encrypted output (guide section 2.5) |
| Public subnet (AWS-6) | private subnets + VPC endpoints (guide step 2) |
| One person is both key admin and data owner | different people; CloudTrail as the audit trail |
| Terraform runs as the root user (AWS-11) | a dedicated IAM identity with MFA; root locked away; no account delegation in the key policy |
| PCR0 pinned by hand | CI builds the image and opens a reviewed change; optionally PCR8 signing (guide step 6) |
| One EC2 instance (AWS-4) | EKS with Jobs and scale to zero (paths doc, Tier 2) |

## Future implementation: gaps to close before real data

Found on 2026-10-02 by reviewing the pattern against the code. None of them affected the POC (synthetic data, a new instance that only you could reach), but each one matters as soon as the data is real. Trust leaks in three places: **what leaves** the enclave (F1), **what gets pinned** (F2) and **who pins** (F3). F4 and F5 are smaller. Full explanation: handbook, sections 40.2 and 40.3.

| # | Gap | Where in the code | What an attacker does | Fix |
|---|---|---|---|---|
| **F1** | The parent receives the report in clear, and can ask for more | `run_job.py` saves and uploads the report (AWS-8); `serve()` in `enclave_app.py` answers any request | root on the parent sends any envelope from `input/` to the enclave and reads the answer. KMS checks *which code* asks for the key, not *who told it to run* | seal the output inside the enclave (guide section 2.5): a new data key from KMS with attestation, AES-GCM on the report, only ciphertext leaves, plus a status (counts, `rules_version`, hash). Optionally accept only jobs signed by the data owner |
| **F2** | The pinned PCR0 was measured on the untrusted parent, and the build is not reproducible | `build_enclave.sh` builds on the EC2 parent; `Dockerfile`: `FROM amazonlinux:2023` without a digest, `dnf install` takes the newest packages | a change made *before* the build is measured and pinned like the real code: a perfect seal on the wrong box | pin every input (base image by digest, package versions, kmstool commit); build on a trusted machine; two independent builds must give the same PCR0; keep a release record (below); optionally sign the image and pin PCR8 |
| **F3** | The key admin can rewrite the rules | `infra/base/kms.tf`: `kms:Put*` includes `kms:PutKeyPolicy`, `kms:Create*` includes `kms:CreateGrant` | adds Decrypt for themselves, pins the PCR0 of a leaking image (it looks like a normal update), or creates a grant that never shows in the policy. True with a dedicated IAM admin too, not only with root (AWS-11) | split duties: the key admin doesn't approve PCR0, a second person reviews every policy change, a pipeline applies it. Drop `kms:Create*` or restrict grants (`kms:GrantIsForAWSResource`). An EventBridge alarm on `PutKeyPolicy` and `CreateGrant`. A test that the policy has exactly 3 statements and `ListGrants` is empty |
| **F4** | The report's hash doesn't prove where the report came from | `report_sha256` in `enclave_app.py`, checked by `run_job.py`, travels in the same message | a tampered parent changes the report and its hash together | the enclave signs the report with a key bound to its attestation |
| **F5** | The enclave doesn't know which dataset it should process | no KMS encryption context (kmstool can't pass one); the dataset id comes from the envelope itself | the parent replays an older envelope, and the enclave processes it | the job request names the expected dataset id, signed by the data owner |

On your own hardware (AMD SEV-SNP or Intel TDX instead of Nitro) the same five gaps apply. F2 and F3 get harder: the measurement also covers the VM firmware and kernel, and the policy admin becomes the admin of your own key broker, without CloudTrail. One gap is added: debug mode is a separate field in the report, not part of the measurement, so the key broker must refuse it explicitly.

### Linking the pin to the source code (F2)

PCR0 is the fingerprint of the **image bytes**, not of the source code.

- **Covered directly:** our Python code. The Dockerfile copies `payroll_rules.py`, `reconcile.py`, `envelope.py`, `vsock_proto.py` and `enclave_app.py` into the image, so one changed character in a formula gives a new PCR0.
- **Covered only as binaries:** the parts that arrive pre-built: kmstool, the Python interpreter, the `cryptography` library, the base OS packages.
- **Not covered:** the recipe (Dockerfile, versions, build machine), only its result.

**Can the source be attached later?** Yes, but only a **reproducible build** makes the attachment provable: anyone takes the tagged source, rebuilds it, and must obtain the pinned PCR0. Without it, as today, attaching the source later is only our word. The session-1 image can no longer be linked: its EIF was deleted with the bucket, and the build cannot be repeated byte for byte.

The release pipeline for a future version:

1. Commit the source with a clean working tree, and tag it (`enclave-vN`).
2. Write the commit id into the image (`/app/BUILD_INFO`), so PCR0 covers it too. The enclave puts it in its status line, so every report says which code produced it.
3. Build on a trusted machine (laptop or CI) with every input pinned: base image by digest, package versions, kmstool commit. Never on the parent.
4. Build a second time, independently. The two PCR0 values must match.
5. Write the **release record**: commit, tag, base image digest, package versions, kmstool commit, PCR0/1/2 (and PCR8 if signed), date, who built it. Keep it in git next to the tag, and in S3 next to the image.
6. Optionally sign the image (`nitro-cli build-enclave --signing-certificate … --private-key …`) and pin PCR8 as well: then KMS accepts only images you signed.
7. Open a reviewed change with the new PCR0. A second person checks it against the release record and approves; the pipeline applies it.
8. The parent only downloads the image and runs it.

## How to run what exists today

```bash
cd poc/payslip
python3 -m unittest                  # 47 tests: formulas, reconciliation, dataset, envelope, encryption, scoring
(cd ../enclave && python3 -m unittest)   # 23 tests: vsock framing, enclave app (local dry run 29/0/0), parent runner
python3 generate_dataset.py          # regenerates data/ (same seed -> same files)
python3 reconcile.py ../../data/payslips-2026-H1.json \
    --answer-key ../../data/answer-key-2026-H1.json
                                     # 580 checked, 29 with differences: 29 matched, 0 missed, 0 unexpected

# Terraform, offline (mock AWS provider, no account needed); requires Terraform >= 1.6
terraform -chdir=infra/base init && terraform -chdir=infra/base test    # 4 tests
```

## Documents

| File | Content |
|---|---|
| `poc/procedures/Lab-phase-terraform.docx` | **procedure, lab phase**: upload the source, create the lab, build the enclave image, pin PCR0, run Mode A in the enclave, test B1, score, destroy |
| `poc/procedures/Base-phase-terraform.docx` | **procedure, base phase**: install Terraform, apply base, encrypt + push the payslips, test B2. Commands, what to watch, troubleshooting, checklist, session log |
| `confidential-poc-handbook.docx` | **the complete study handbook** (68 pages, v1.1, with the future-implementation gaps in section 40): everything we did, why, and how it works in depth |
| `poc-tier1-spec.docx` | **the full design of the POC we deploy**: architecture, key policy, enclave, runbook, safety nets |
| `confidential-processing-aws-study-guide-v2.docx` | Part I: the big picture and concepts · Part II: the original build plan · Part III: exam corner |
| `payslip-poc-data-dictionary.docx` | fields, formulas, planted errors |
| `poc-deployment-paths-ec2-vs-eks.docx` | Tier 1 (EC2) vs Tier 2 (EKS), costs in Stockholm |

## What's next

1. **Close the gaps F1–F5** before any real data (section *Future implementation* above). F1 (sealed output) and F2 (reproducible build, release record) come first.
2. **Run it again** to record the status line, tests B1/B2 and the score: the formal proof the first run missed.
