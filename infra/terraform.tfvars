aws_region = "us-east-1"

project_name = "hello-world-api"
environment  = "dev"

ecr_repository_name = "hello-world-lambda"
image_tag           = "latest"

stage_name = "dev"

lambda_timeout     = 30  # seconds
lambda_memory_size = 512 # MB

log_retention_days = 7 # days
