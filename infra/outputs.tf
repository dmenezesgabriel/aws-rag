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

output "lambda_function_name" {
  description = "Name of the Lambda function"
  value       = aws_lambda_function.api_lambda.function_name
}

output "lambda_function_arn" {
  description = "ARN of the Lambda function"
  value       = aws_lambda_function.api_lambda.arn
}

output "lambda_log_group" {
  description = "CloudWatch log group for Lambda function"
  value       = aws_cloudwatch_log_group.lambda_logs.name
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
  value       = "${aws_ecr_repository.lambda_repo.repository_url}@${docker_registry_image.lambda_image.sha256_digest}"
}

output "region" {
  description = "AWS region where resources are deployed"
  value       = var.aws_region
}

output "test_commands" {
  description = "Commands to test your API endpoints"
  value       = <<-EOT
    # Test the hello endpoint
    curl ${aws_api_gateway_stage.api_stage.invoke_url}/hello

    # Test with a name parameter
    curl ${aws_api_gateway_stage.api_stage.invoke_url}/hello/YourName

    # Test health endpoint
    curl ${aws_api_gateway_stage.api_stage.invoke_url}/health
  EOT
}

output "monitoring_commands" {
  description = "Commands to monitor your application"
  value       = <<-EOT
    # View Lambda logs (live tail)
    aws logs tail "${aws_cloudwatch_log_group.lambda_logs.name}" --follow

    # View API Gateway logs (live tail)
    aws logs tail "${aws_cloudwatch_log_group.api_gateway_logs.name}" --follow

    # Get Lambda function info
    aws lambda get-function --function-name ${aws_lambda_function.api_lambda.function_name}

    # View Lambda metrics
    aws cloudwatch get-metric-statistics \
      --namespace AWS/Lambda \
      --metric-name Invocations \
      --dimensions Name=FunctionName,Value=${aws_lambda_function.api_lambda.function_name} \
      --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
      --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
      --period 300 \
      --statistics Sum
  EOT
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
