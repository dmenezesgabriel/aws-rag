variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
  default     = "hello-world-api"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "ecr_repository_name" {
  description = "Name of the ECR repository for Lambda container images"
  type        = string
  default     = "hello-world-lambda"
}

variable "image_tag" {
  description = "Docker image tag for the Lambda container"
  type        = string
  default     = "latest"
}

variable "stage_name" {
  description = "API Gateway stage name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "lambda_timeout" {
  description = "Lambda function timeout in seconds"
  type        = number
  default     = 30
}

variable "lambda_memory_size" {
  description = "Lambda function memory size in MB"
  type        = number
  default     = 512
}

variable "log_retention_days" {
  description = "CloudWatch log retention period in days"
  type        = number
  default     = 7
}

variable "bedrock_model_id" {
  description = "Bedrock model ID for chat completions"
  type        = string
  default     = "anthropic.claude-3-sonnet-20240229-v1:0"
}
