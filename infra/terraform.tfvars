aws_region = "us-east-1"

project_name = "llm-chat-api"
environment  = "dev"

ecr_repository_name = "llm-chat-lambda"
image_tag           = "latest"

stage_name = "dev"

lambda_timeout     = 30  # seconds
lambda_memory_size = 512 # MB

log_retention_days = 7 # days

bedrock_model_id = "amazon.nova-lite-v1:0"
