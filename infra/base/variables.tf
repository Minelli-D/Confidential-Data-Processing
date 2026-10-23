variable "region" {
  type        = string
  description = "AWS Region for the POC (decision 1: Stockholm)"
  default     = "eu-north-1"
}

variable "name_prefix" {
  type        = string
  description = "Prefix for resource names"
  default     = "confidential-poc"
}

variable "budget_email" {
  type        = string
  description = "Email that receives the budget alerts (asked at apply time, never stored in code)"
}

variable "budget_limit_usd" {
  type        = number
  description = "Monthly budget for the whole account, in USD"
  default     = 5
}

variable "enclave_pcr0" {
  type        = string
  description = "PCR0 of the approved enclave image. Leave null on the first apply: the enclave statement is added once the image is built."
  default     = null

  validation {
    condition = var.enclave_pcr0 == null || (
      can(regex("^[0-9a-fA-F]{96}$", var.enclave_pcr0)) &&
      lower(coalesce(var.enclave_pcr0, "x")) != join("", [for i in range(96) : "0"])
    )
    error_message = "PCR0 must be a 96-character SHA-384 hex value and must not be the debug-mode value (all zeros)."
  }
}
