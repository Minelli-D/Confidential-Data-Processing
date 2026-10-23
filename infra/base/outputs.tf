output "region" {
  value = var.region
}

output "key_arn" {
  value = aws_kms_key.poc.arn
}

output "key_alias" {
  value = aws_kms_alias.poc.name
}

output "bucket_name" {
  value = aws_s3_bucket.poc.bucket
}

output "instance_role_arn" {
  value = aws_iam_role.instance.arn
}

output "instance_profile_name" {
  value = aws_iam_instance_profile.instance.name
}

output "pcr0_pinned" {
  description = "true once the key policy contains the enclave statement (first session, step 7)"
  value       = var.enclave_pcr0 != null
}
