# Two availability zones, three tiers of subnet:
#   public  - load balancer and NAT gateway(s); the only tier reachable from the internet
#   app     - Fargate tasks; outbound internet (LLM APIs, SES) via NAT, no inbound except from the ALB
#   db      - RDS; no route to the internet at all

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs     = slice(data.aws_availability_zones.available.names, 0, 2)
  nat_azs = var.nat_gateway_per_az ? local.azs : [local.azs[0]]
  # Subnet i of each tier is in local.azs[i]; e.g. with 10.40.0.0/16:
  # public 10.40.0-1.0/24, app 10.40.10-11.0/24, db 10.40.20-21.0/24.
  public_cidrs = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, i)]
  app_cidrs    = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, 10 + i)]
  db_cidrs     = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, 20 + i)]
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = var.name }
}

# Remove the rules from the VPC's default security group so nothing can use it by accident.
resource "aws_default_security_group" "default" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.name}-default-unused" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = var.name }
}

# --- Public tier -----------------------------------------------------------

resource "aws_subnet" "public" {
  count             = length(local.azs)
  vpc_id            = aws_vpc.main.id
  availability_zone = local.azs[count.index]
  cidr_block        = local.public_cidrs[count.index]
  tags              = { Name = "${var.name}-public-${local.azs[count.index]}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.name}-public" }

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
}

resource "aws_route_table_association" "public" {
  count          = length(local.azs)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_eip" "nat" {
  count  = length(local.nat_azs)
  domain = "vpc"
  tags   = { Name = "${var.name}-nat-${local.nat_azs[count.index]}" }
}

resource "aws_nat_gateway" "main" {
  count         = length(local.nat_azs)
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id
  tags          = { Name = "${var.name}-${local.nat_azs[count.index]}" }

  depends_on = [aws_internet_gateway.main]
}

# --- App tier --------------------------------------------------------------

resource "aws_subnet" "app" {
  count             = length(local.azs)
  vpc_id            = aws_vpc.main.id
  availability_zone = local.azs[count.index]
  cidr_block        = local.app_cidrs[count.index]
  tags              = { Name = "${var.name}-app-${local.azs[count.index]}" }
}

resource "aws_route_table" "app" {
  count  = length(local.azs)
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.name}-app-${local.azs[count.index]}" }

  route {
    cidr_block = "0.0.0.0/0"
    # With a single NAT gateway, both AZs share it.
    nat_gateway_id = aws_nat_gateway.main[min(count.index, length(local.nat_azs) - 1)].id
  }
}

resource "aws_route_table_association" "app" {
  count          = length(local.azs)
  subnet_id      = aws_subnet.app[count.index].id
  route_table_id = aws_route_table.app[count.index].id
}

# Free gateway endpoint: container image layers (stored in S3) bypass the NAT
# gateway, which avoids NAT data charges on every deploy.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = aws_route_table.app[*].id
  tags              = { Name = "${var.name}-s3" }
}

# --- Database tier -----------------------------------------------------------

resource "aws_subnet" "db" {
  count             = length(local.azs)
  vpc_id            = aws_vpc.main.id
  availability_zone = local.azs[count.index]
  cidr_block        = local.db_cidrs[count.index]
  tags              = { Name = "${var.name}-db-${local.azs[count.index]}" }
}

# No routes beyond the VPC itself.
resource "aws_route_table" "db" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.name}-db" }
}

resource "aws_route_table_association" "db" {
  count          = length(local.azs)
  subnet_id      = aws_subnet.db[count.index].id
  route_table_id = aws_route_table.db.id
}
