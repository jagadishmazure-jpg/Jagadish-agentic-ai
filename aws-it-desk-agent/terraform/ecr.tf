resource "aws_ecr_repository" "agent" {
  name                 = "it-desk-playbook"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.logs.arn
  }
}
