variable "region" {
  type        = string
  description = "Must match base"
  default     = "eu-north-1"
}

variable "name_prefix" {
  type    = string
  default = "confidential-poc"
}

variable "instance_type" {
  type        = string
  description = "Decision 9: 4 vCPU / 16 GiB, enclaves supported"
  default     = "m6i.xlarge"
}

variable "use_spot" {
  type        = bool
  description = "Decision 10: On-Demand by default. true = one-time Spot request, terminated on interruption"
  default     = false
}

variable "enclave_cpu_count" {
  type        = number
  description = "vCPUs set aside for the enclave (taken away from the parent)"
  default     = 2
}

variable "enclave_memory_mib" {
  type        = number
  description = "Memory set aside for the enclave. Raise it if run-enclave reports insufficient memory"
  default     = 4096
}

variable "self_destruct_hours" {
  type        = number
  description = "Safety net 2: the instance shuts down (and so terminates) this many hours after boot"
  default     = 4
}

variable "root_volume_gb" {
  type        = number
  description = "Room for the Docker build of the enclave image"
  default     = 30
}
