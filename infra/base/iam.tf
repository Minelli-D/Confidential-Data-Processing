# The EC2 instance identity lives in base, not lab: if a role named in a key policy is deleted and
# recreated, the key policy no longer recognises it (spec, section 3). IAM roles are free.

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "instance" {
  name               = "${var.name_prefix}-instance"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

# SSM Session Manager: shell access without SSH and without inbound ports
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# S3 only. No KMS permissions here: the key policy names the role directly (row 3)
data "aws_iam_policy_document" "instance_s3" {
  statement {
    sid       = "ReadInputAndEnclave"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.poc.arn}/input/*", "${aws_s3_bucket.poc.arn}/enclave/*"]
  }
  statement {
    sid       = "WriteReportsAndEnclaveImage"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.poc.arn}/reports/*", "${aws_s3_bucket.poc.arn}/enclave/*"]
  }
  statement {
    sid       = "ListBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.poc.arn]
  }
}

resource "aws_iam_role_policy" "instance_s3" {
  name   = "s3-poc-bucket"
  role   = aws_iam_role.instance.id
  policy = data.aws_iam_policy_document.instance_s3.json
}

resource "aws_iam_instance_profile" "instance" {
  name = "${var.name_prefix}-instance"
  role = aws_iam_role.instance.name
}
