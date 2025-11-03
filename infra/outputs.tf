output "api_endpoint" {
  description = "Base URL for the API Gateway stage"
  value       = aws_api_gateway_stage.api_stage.invoke_url
}

output "api_id" {
  description = "API Gateway REST API ID"
  value       = aws_api_gateway_rest_api.api.id
}

output "api_stage" {
  description = "API Gateway stage name"
  value       = aws_api_gateway_stage.api_stage.stage_name
}

output "worker_lambda_function_name" {
  description = "Name of the Worker Lambda function"
  value       = aws_lambda_function.worker_lambda.function_name
}

output "api_lambda_log_group" {
  description = "CloudWatch log group for API Lambda"
  value       = aws_cloudwatch_log_group.api_lambda_logs.name
}

output "worker_lambda_log_group" {
  description = "CloudWatch log group for Worker Lambda"
  value       = aws_cloudwatch_log_group.worker_lambda_logs.name
}

output "ecr_repository_url" {
  description = "ECR repository URL for the Lambda container image"
  value       = aws_ecr_repository.lambda_repo.repository_url
}

output "ecr_repository_name" {
  description = "ECR repository name"
  value       = aws_ecr_repository.lambda_repo.name
}

output "docker_image_uri" {
  description = "Full Docker image URI with digest"
  value       = "${aws_ecr_repository.lambda_repo.repository_url}@${docker_registry_image.worker_lambda_image.sha256_digest}"
}

output "region" {
  description = "AWS region where resources are deployed"
  value       = var.aws_region
}

output "deployment_info" {
  description = "Deployment information summary"
  value = {
    api_endpoint    = aws_api_gateway_stage.api_stage.invoke_url
    lambda_function = aws_lambda_function.api_lambda.function_name
    ecr_repository  = aws_ecr_repository.lambda_repo.repository_url
    environment     = var.environment
    region          = var.aws_region
    build_system    = "UV with pyproject.toml"
  }
}
