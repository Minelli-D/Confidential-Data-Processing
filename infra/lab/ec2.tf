# The parent instance: Amazon Linux 2023, enclaves on, IMDSv2 only, self-destructs after a few hours
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_instance" "parent" {
  ami                    = data.aws_ssm_parameter.al2023.insecure_value
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.instance.id]
  iam_instance_profile   = data.terraform_remote_state.base.outputs.instance_profile_name

  # Safety net 2: "shutdown" in the startup script terminates the instance instead of stopping it
  instance_initiated_shutdown_behavior = "terminate"

  enclave_options {
    enabled = true
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gb
    encrypted             = true
    delete_on_termination = true
  }

  dynamic "instance_market_options" {
    for_each = var.use_spot ? [1] : []
    content {
      market_type = "spot"
      spot_options {
        spot_instance_type             = "one-time"
        instance_interruption_behavior = "terminate"
      }
    }
  }

  user_data = templatefile("${path.module}/user-data.sh.tftpl", {
    region                = var.region
    bucket                = data.terraform_remote_state.base.outputs.bucket_name
    enclave_cpu_count     = var.enclave_cpu_count
    enclave_memory_mib    = var.enclave_memory_mib
    self_destruct_minutes = var.self_destruct_hours * 60
  })
  user_data_replace_on_change = true

  tags = { Name = "${var.name_prefix}-parent" }
}
