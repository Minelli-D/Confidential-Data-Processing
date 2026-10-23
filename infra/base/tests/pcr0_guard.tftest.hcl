# Offline test (mock AWS provider, no account needed): terraform -chdir=infra/base test
# Proves the debug-mode guard: a zero or malformed PCR0 can never reach the key policy.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
      arn        = "arn:aws:iam::123456789012:user/poc-admin"
    }
  }
  mock_data "aws_iam_session_context" {
    defaults = {
      issuer_arn = "arn:aws:iam::123456789012:user/poc-admin"
    }
  }
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{}"
    }
  }
}

variables {
  budget_email = "budget@example.com"
}

run "first_apply_without_pcr0_is_allowed" {
  command = plan

  assert {
    condition     = output.pcr0_pinned == false
    error_message = "Without PCR0 the enclave statement must not be in the key policy"
  }
}

run "debug_mode_pcr0_all_zeros_is_refused" {
  command = plan
  variables {
    enclave_pcr0 = "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
  }
  expect_failures = [var.enclave_pcr0]
}

run "malformed_pcr0_is_refused" {
  command = plan
  variables {
    enclave_pcr0 = "not-a-sha384-hash"
  }
  expect_failures = [var.enclave_pcr0]
}

run "real_pcr0_is_accepted" {
  command = plan
  variables {
    enclave_pcr0 = "160927695811bac4226cbb17f0923a45253b4b56f295fee99807a6874a679e596b6ffb89dacff27749f9993450f79b2e"
  }

  assert {
    condition     = output.pcr0_pinned == true
    error_message = "A valid PCR0 must add the enclave statement"
  }
}
