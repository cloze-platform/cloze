# PostgreSQL on RDS: private subnets only, encrypted with the instance key,
# TLS required for every connection.
#
# The master password is generated here and handed to the app inside
# DATABASE_URL (see secrets.tf). It is not auto-rotated: the app reads
# DATABASE_URL once at startup, so a rotation would break new connections
# until every task restarted.

resource "random_password" "db" {
  length  = 40
  special = false # keeps DATABASE_URL free of characters that need escaping
}

resource "aws_db_subnet_group" "main" {
  name       = var.name
  subnet_ids = aws_subnet.db[*].id
}

resource "aws_db_parameter_group" "main" {
  name_prefix = "${var.name}-pg${var.db_engine_version}-"
  family      = "postgres${var.db_engine_version}"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_instance" "main" {
  identifier     = var.name
  engine         = "postgres"
  engine_version = var.db_engine_version
  instance_class = var.db_instance_class

  db_name  = "cloze"
  username = "cloze"
  password = random_password.db.result

  allocated_storage     = var.db_allocated_storage_gb
  max_allocated_storage = var.db_max_allocated_storage_gb
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.data.arn

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  parameter_group_name   = aws_db_parameter_group.main.name
  publicly_accessible    = false
  multi_az               = var.db_multi_az

  backup_retention_period    = var.db_backup_retention_days
  backup_window              = "07:00-08:00" # UTC = 2-3am / 3-4am US Eastern
  maintenance_window         = "sun:08:00-sun:09:00"
  auto_minor_version_upgrade = true
  copy_tags_to_snapshot      = true

  deletion_protection       = var.db_deletion_protection
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.name}-final"
}
