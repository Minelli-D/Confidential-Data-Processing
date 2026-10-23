output "instance_id" {
  value = aws_instance.parent.id
}

output "purchasing" {
  value = var.use_spot ? "spot (one-time)" : "on-demand"
}

output "ssm_session_command" {
  description = "Open a shell on the parent (needs the Session Manager plugin on your laptop)"
  value       = "aws ssm start-session --target ${aws_instance.parent.id} --region ${var.region}"
}

output "self_destruct" {
  value = "the instance terminates itself ${var.self_destruct_hours} hours after boot (cancel with: sudo shutdown -c)"
}

output "bucket_name" {
  value = data.terraform_remote_state.base.outputs.bucket_name
}
