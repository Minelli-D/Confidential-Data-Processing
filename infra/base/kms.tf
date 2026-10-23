# One KMS key for the whole POC (decision 3): created once, never rotated, never destroyed by Terraform.
# There is deliberately NO "account root" statement: only this key policy decides who can use the key,
# so no IAM policy in the account can grant Decrypt (spec, section 4).

data "aws_caller_identity" "current" {}

# The identity that runs Terraform, as a stable IAM ARN (role ARN for assumed roles, user ARN for IAM users)
data "aws_iam_session_context" "current" {
  arn = data.aws_caller_identity.current.arn
}

locals {
  me = data.aws_iam_session_context.current.issuer_arn
}

data "aws_iam_policy_document" "key" {
  # Row 1: you manage the key, but you can never decrypt with it
  statement {
    sid = "KeyAdministrationNoDecrypt"
    actions = [
      "kms:Create*", "kms:Describe*", "kms:Enable*", "kms:List*", "kms:Put*", "kms:Update*",
      "kms:Revoke*", "kms:Disable*", "kms:Get*", "kms:Delete*", "kms:TagResource", "kms:UntagResource",
      "kms:ScheduleKeyDeletion", "kms:CancelKeyDeletion",
    ]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = [local.me]
    }
  }

  # Row 2: you, as data owner, can encrypt (envelope encryption on the laptop) but not decrypt
  statement {
    sid       = "DataOwnerEncryptOnly"
    actions   = ["kms:GenerateDataKey", "kms:Encrypt", "kms:DescribeKey"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = [local.me]
    }
  }

  # Row 3: the instance role can decrypt ONLY with an attestation document showing the approved PCR0.
  # Added only after the enclave image is built (first session, step 7).
  dynamic "statement" {
    for_each = var.enclave_pcr0 == null ? [] : [var.enclave_pcr0]
    content {
      sid       = "EnclaveDecryptOnlyWithAttestation"
      actions   = ["kms:Decrypt"]
      resources = ["*"]
      principals {
        type        = "AWS"
        identifiers = [aws_iam_role.instance.arn]
      }
      condition {
        test     = "StringEqualsIgnoreCase"
        variable = "kms:RecipientAttestation:ImageSha384"
        values   = [statement.value]
      }
    }
  }
}

resource "aws_kms_key" "poc" {
  description             = "Confidential POC: payslips decryptable only by the attested enclave"
  enable_key_rotation     = false # decision 3: each rotation would add $1/month
  deletion_window_in_days = 7
  policy                  = data.aws_iam_policy_document.key.json

  lifecycle {
    prevent_destroy = true # set to false only to delete base at the end of a run (done once on 2026-10-01, 16:50)
  }
}

resource "aws_kms_alias" "poc" {
  name          = "alias/${var.name_prefix}"
  target_key_id = aws_kms_key.poc.key_id
}
