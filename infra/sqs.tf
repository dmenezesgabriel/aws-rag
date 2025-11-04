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
