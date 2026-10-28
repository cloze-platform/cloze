# The master user owns the schema and is only used by the admin task (setup and
# migrations). The app connects as cloze_app, which `manage.py init-production`
# creates with row access only. Neither password is auto-rotated: the app only
# reads DATABASE_URL at startup.

resource "random_password" "db" {
  length  = 40
  special = false # nothing to URL-escape in DATABASE_URL
}

resource "random_password" "db_app" {
  length  = 40
  special = false
}

resource "aws_db_subnet_group" "main" {
  name       = var.name
  subnet_ids = aws_subnet.db[*].id
}

resource "aws_db_parameter_group" "main" {
  name_prefix = "${var.name}-pg${var.db_engine_version}-"
  family      = "postgres${var.db_engine_version}"

  # Already the default since PostgreSQL 15; set so it can't be switched off.
  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot" # how RDS reports it; anything else diffs on every plan
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
