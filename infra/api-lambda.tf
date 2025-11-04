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

resource "aws_cloudwatch_log_group" "api_lambda_logs" {
  name              = "/aws/lambda/${aws_lambda_function.api_lambda.function_name}"
  retention_in_days = var.log_retention_days

  tags = {
    Name        = "${var.project_name}-api-lambda-logs"
    Environment = var.environment
  }
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_lambda.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/*"
}
