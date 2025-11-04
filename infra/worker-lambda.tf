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
