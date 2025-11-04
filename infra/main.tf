terraform {
  required_version = ">= 1.0"

  backend "s3" {
    bucket  = "tfstate-chatbot-api"
    key     = "infra/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}
data "aws_ecr_authorization_token" "token" {}

provider "docker" {
  registry_auth {
    address  = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
    username = data.aws_ecr_authorization_token.token.user_name
    password = data.aws_ecr_authorization_token.token.password
  }
}

# ==================== DynamoDB Table ====================
resource "aws_dynamodb_table" "conversations" {
  name         = "${var.project_name}-conversations"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  attribute {
    name = "session_status"
    type = "S"
  }

  # GSI for querying by session status
  global_secondary_index {
    name            = "SessionStatusIndex"
    hash_key        = "session_status"
    range_key       = "SK"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Name        = "${var.project_name}-conversations"
    Environment = var.environment
  }
}

# ==================== SQS Queue ====================
resource "aws_sqs_queue" "chat_tasks_dlq" {
  name                      = "${var.project_name}-chat-tasks-dlq"
  message_retention_seconds = 1209600 # 14 days

  tags = {
    Name        = "${var.project_name}-chat-tasks-dlq"
    Environment = var.environment
  }
}

resource "aws_sqs_queue" "chat_tasks" {
  name                       = "${var.project_name}-chat-tasks"
  visibility_timeout_seconds = 300    # 5 minutes (should be >= lambda timeout)
  message_retention_seconds  = 345600 # 4 days
  receive_wait_time_seconds  = 20     # Long polling

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.chat_tasks_dlq.arn
    maxReceiveCount     = 3
  })

  tags = {
    Name        = "${var.project_name}-chat-tasks"
    Environment = var.environment
  }
}

resource "aws_lambda_event_source_mapping" "worker_sqs_trigger" {
  event_source_arn = aws_sqs_queue.chat_tasks.arn
  function_name    = aws_lambda_function.worker_lambda.arn
  batch_size       = 1
  enabled          = true
}
# ==================== ECR Repository ====================
resource "aws_ecr_repository" "lambda_repo" {
  name                 = var.ecr_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  force_delete = true

  tags = {
    Name        = var.ecr_repository_name
    Environment = var.environment
  }
}

# ==================== Docker Image Build ====================
resource "null_resource" "worker_lambda_code_hash" {
  triggers = {
    code_hash = sha256(join("", [
      filesha256(abspath("${path.module}/../worker_lambda/worker.py")),
      filesha256(abspath("${path.module}/../worker_lambda/pyproject.toml")),
      filesha256(abspath("${path.module}/../worker_lambda/Dockerfile"))
    ]))
  }
}

resource "docker_image" "worker_lambda_image" {
  name = "${aws_ecr_repository.lambda_repo.repository_url}:${var.image_tag}"

  build {
    context  = abspath("${path.module}/../worker_lambda")
    tag      = ["${aws_ecr_repository.lambda_repo.repository_url}:${var.image_tag}"]
    platform = "linux/amd64"
  }

  triggers = {
    code_hash = null_resource.worker_lambda_code_hash.triggers.code_hash
  }
}

resource "docker_registry_image" "worker_lambda_image" {
  name = docker_image.worker_lambda_image.name

  triggers = {
    code_hash = null_resource.worker_lambda_code_hash.triggers.code_hash
  }

  keep_remotely = true
}

# ==================== IAM Role for API Lambda ====================
resource "aws_iam_role" "api_lambda_role" {
  name = "${var.project_name}-api-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name        = "${var.project_name}-api-lambda-role"
    Environment = var.environment
  }
}

resource "aws_iam_role_policy_attachment" "api_lambda_basic" {
  role       = aws_iam_role.api_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "api_lambda_xray" {
  role       = aws_iam_role.api_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

# Policy for API Lambda to access DynamoDB and SQS
resource "aws_iam_role_policy" "api_lambda_policy" {
  name = "${var.project_name}-api-lambda-policy"
  role = aws_iam_role.api_lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:UpdateItem"
        ]
        Resource = [
          aws_dynamodb_table.conversations.arn,
          "${aws_dynamodb_table.conversations.arn}/index/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:GetQueueUrl"
        ]
        Resource = aws_sqs_queue.chat_tasks.arn
      }
    ]
  })
}

# ==================== IAM Role for Worker Lambda ====================
resource "aws_iam_role" "worker_lambda_role" {
  name = "${var.project_name}-worker-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = {
    Name        = "${var.project_name}-worker-lambda-role"
    Environment = var.environment
  }
}


resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.worker_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_xray" {
  role       = aws_iam_role.worker_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

resource "aws_iam_role_policy_attachment" "worker_sqs" {
  role       = aws_iam_role.worker_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaSQSQueueExecutionRole"
}

resource "aws_iam_role_policy" "worker_lambda_policy" {
  name = "${var.project_name}-worker-lambda-policy"
  role = aws_iam_role.worker_lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:UpdateItem"
        ]
        Resource = [
          aws_dynamodb_table.conversations.arn,
          "${aws_dynamodb_table.conversations.arn}/index/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = "arn:aws:bedrock:${var.aws_region}::foundation-model/*"
      }
    ]
  })
}

# ==================== API Lambda Function (Non-container) ====================
resource "null_resource" "build_api_lambda" {
  triggers = {
    source_hash = sha256(join("", [
      filesha256("${path.module}/../api_lambda/api.py"),
      filesha256("${path.module}/../api_lambda/requirements.txt")
    ]))
  }

  provisioner "local-exec" {
    command = <<EOT
      set -e
      BUILD_DIR=.terraform/api_lambda_build
      REQUIREMENTS_FILE=../api_lambda/requirements.txt

      rm -rf $BUILD_DIR
      mkdir -p $BUILD_DIR
      cp ../api_lambda/api.py $BUILD_DIR/
      cp $REQUIREMENTS_FILE $BUILD_DIR/

      pip install \
        --target $BUILD_DIR \
        -r $BUILD_DIR/requirements.txt \
        --platform manylinux2014_x86_64 \
        --only-binary :all: \
        --implementation cp \
        --python-version 3.12 \
        --upgrade \
        --no-cache-dir

      cd $BUILD_DIR
      zip -r ../api_lambda.zip .
    EOT
    # Run the command from the module root for correct relative paths
    working_dir = path.module
  }
}

data "archive_file" "api_lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/.terraform/api_lambda_build"
  output_path = "${path.module}/.terraform/api_lambda.zip"

  depends_on = [null_resource.build_api_lambda]
}

resource "aws_lambda_function" "api_lambda" {
  filename         = data.archive_file.api_lambda_zip.output_path
  function_name    = "${var.project_name}-api"
  role             = aws_iam_role.api_lambda_role.arn
  handler          = "api.lambda_handler"
  runtime          = "python3.12"
  timeout          = 30
  memory_size      = 512
  source_code_hash = data.archive_file.api_lambda_zip.output_base64sha256

  environment {
    variables = {
      POWERTOOLS_SERVICE_NAME      = "${var.project_name}-api"
      LOG_LEVEL                    = "INFO"
      POWERTOOLS_METRICS_NAMESPACE = "${var.project_name}-api"
      DYNAMODB_TABLE               = aws_dynamodb_table.conversations.name
      SQS_QUEUE_URL                = aws_sqs_queue.chat_tasks.url
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = {
    Name        = "${var.project_name}-api"
    Environment = var.environment
  }
}

resource "aws_cloudwatch_log_group" "api_lambda_logs" {
  name              = "/aws/lambda/${aws_lambda_function.api_lambda.function_name}"
  retention_in_days = var.log_retention_days

  tags = {
    Name        = "${var.project_name}-api-lambda-logs"
    Environment = var.environment
  }
}


# ==================== Worker Lambda Function (Container) ====================
resource "aws_lambda_function" "worker_lambda" {
  function_name = "${var.project_name}-worker"
  role          = aws_iam_role.worker_lambda_role.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.lambda_repo.repository_url}@${docker_registry_image.worker_lambda_image.sha256_digest}"
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory_size

  environment {
    variables = {
      POWERTOOLS_SERVICE_NAME      = "${var.project_name}-worker"
      LOG_LEVEL                    = "INFO"
      POWERTOOLS_METRICS_NAMESPACE = "${var.project_name}-worker"
      DYNAMODB_TABLE               = aws_dynamodb_table.conversations.name
      BEDROCK_MODEL_ID             = var.bedrock_model_id
      SQS_QUEUE_URL                = aws_sqs_queue.chat_tasks.url
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = {
    Name        = "${var.project_name}-worker"
    Environment = var.environment
  }
}

resource "aws_cloudwatch_log_group" "worker_lambda_logs" {
  name              = "/aws/lambda/${aws_lambda_function.worker_lambda.function_name}"
  retention_in_days = var.log_retention_days

  tags = {
    Name        = "${var.project_name}-worker-lambda-logs"
    Environment = var.environment
  }
}

# ==================== API Gateway ====================
resource "aws_api_gateway_rest_api" "api" {
  name        = "${var.project_name}-api"
  description = "REST API for ${var.project_name}"

  body = templatefile("${path.module}/api-spec.yaml", {
    lambda_invoke_arn = aws_lambda_function.api_lambda.invoke_arn
  })

  endpoint_configuration {
    types = ["REGIONAL"]
  }

  tags = {
    Name        = "${var.project_name}-api"
    Environment = var.environment
  }
}

resource "aws_api_gateway_deployment" "api_deployment" {
  rest_api_id = aws_api_gateway_rest_api.api.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_rest_api.api.body,
      aws_lambda_function.api_lambda.qualified_arn
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    aws_api_gateway_rest_api.api
  ]
}

resource "aws_api_gateway_stage" "api_stage" {
  deployment_id = aws_api_gateway_deployment.api_deployment.id
  rest_api_id   = aws_api_gateway_rest_api.api.id
  stage_name    = var.stage_name

  xray_tracing_enabled = true

  tags = {
    Name        = "${var.project_name}-${var.stage_name}"
    Environment = var.environment
  }
}

resource "aws_cloudwatch_log_group" "api_gateway_logs" {
  name              = "/aws/apigateway/${var.project_name}"
  retention_in_days = var.log_retention_days

  tags = {
    Name        = "${var.project_name}-api-logs"
    Environment = var.environment
  }
}

resource "aws_api_gateway_account" "api_gateway_account" {
  cloudwatch_role_arn = aws_iam_role.api_gateway_cloudwatch.arn
}

resource "aws_iam_role" "api_gateway_cloudwatch" {
  name = "${var.project_name}-api-gateway-cloudwatch"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "apigateway.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "api_gateway_cloudwatch" {
  role       = aws_iam_role.api_gateway_cloudwatch.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs"
}

# ==================== Lambda Permissions ====================
resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_lambda.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/*"
}
