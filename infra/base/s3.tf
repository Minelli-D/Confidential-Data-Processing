# The "post office": input/ (encrypted envelope), enclave/ (source, image, PCRs), reports/ (POC: in clear)
resource "aws_s3_bucket" "poc" {
  bucket = "${var.name_prefix}-${data.aws_caller_identity.current.account_id}-${var.region}"
}

resource "aws_s3_bucket_public_access_block" "poc" {
  bucket                  = aws_s3_bucket.poc.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "poc" {
  bucket = aws_s3_bucket.poc.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Layer 2 (at rest): SSE-S3. Our KMS key is NOT used here, so the key policy stays pure (spec, section 3)
resource "aws_s3_bucket_server_side_encryption_configuration" "poc" {
  bucket = aws_s3_bucket.poc.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "poc" {
  bucket = aws_s3_bucket.poc.id
  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

data "aws_iam_policy_document" "bucket" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.poc.arn, "${aws_s3_bucket.poc.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "poc" {
  bucket     = aws_s3_bucket.poc.id
  policy     = data.aws_iam_policy_document.bucket.json
  depends_on = [aws_s3_bucket_public_access_block.poc]
}
