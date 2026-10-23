# Decision 6: one public subnet, no inbound rules, outbound HTTPS only. All of these resources are free.
data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "lab" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "${var.name_prefix}-lab" }
}

resource "aws_internet_gateway" "lab" {
  vpc_id = aws_vpc.lab.id
  tags   = { Name = "${var.name_prefix}-lab" }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.lab.id
  cidr_block              = "10.42.1.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true
  tags                    = { Name = "${var.name_prefix}-lab-public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.lab.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.lab.id
  }
  tags = { Name = "${var.name_prefix}-lab-public" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# Zero ingress rules: nobody can start a connection to the instance (we use SSM).
# Security groups are stateful, so replies to our outbound calls still come back.
resource "aws_security_group" "instance" {
  name        = "${var.name_prefix}-lab-instance"
  description = "No inbound. Outbound HTTPS only (KMS, S3, SSM, packages, container images)"
  vpc_id      = aws_vpc.lab.id

  egress {
    description = "HTTPS out"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Decision AWS-12 (found in the first session): the kmstool build runs in an Amazon Linux 2 container
  # whose yum mirror list is fetched over HTTP. Packages are GPG-signed, so integrity does not rely on TLS.
  # (The description above is left unchanged on purpose: changing it would force a replacement.)
  egress {
    description = "HTTP out: Amazon Linux 2 package mirrors (kmstool build)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
