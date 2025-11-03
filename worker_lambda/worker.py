import json
import os
import uuid
from datetime import datetime

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from boto3.dynamodb.conditions import Key

logger = Logger()
tracer = Tracer()

# AWS Clients
dynamodb = boto3.resource("dynamodb")
bedrock_runtime = boto3.client("bedrock-runtime")

# Environment variables
DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]
BEDROCK_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0"
)

table = dynamodb.Table(DYNAMODB_TABLE)


@tracer.capture_method
def get_conversation_history(user_id: str, session_id: str, limit: int = 10):
    """Fetch recent conversation history from DynamoDB"""
    pk = f"USER#{user_id}#SESSION#{session_id}"

    response = table.query(
        KeyConditionExpression=Key("PK").eq(pk),
        ScanIndexForward=False,  # Most recent first
        Limit=limit,
    )

    messages = response.get("Items", [])
    messages.reverse()  # Chronological order

    return messages


@tracer.capture_method
def build_bedrock_messages(conversation_history):
    """Convert DynamoDB messages to Bedrock format"""
    messages = []

    for msg in conversation_history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    return messages


@tracer.capture_method
def invoke_bedrock(messages):
    """Call Bedrock Claude model"""
    try:
        # Prepare the request body for Claude
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2048,
            "messages": messages,
        }

        logger.info(f"Invoking Bedrock model: {BEDROCK_MODEL_ID}")

        response = bedrock_runtime.invoke_model(
            modelId=BEDROCK_MODEL_ID, body=json.dumps(request_body)
        )

        # Parse response
        response_body = json.loads(response["body"].read())

        # Extract assistant message
        assistant_message = response_body["content"][0]["text"]

        # Get usage metrics
        usage = response_body.get("usage", {})

        return {"content": assistant_message, "usage": usage}

    except Exception as e:
        logger.exception("Error invoking Bedrock")
        raise


@tracer.capture_method
def save_assistant_message(
    user_id: str, session_id: str, content: str, metadata: dict
):
    """Save assistant response to DynamoDB"""
    message_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat() + "Z"

    pk = f"USER#{user_id}#SESSION#{session_id}"
    sk = timestamp

    item = {
        "PK": pk,
        "SK": sk,
        "message_id": message_id,
        "role": "assistant",
        "content": content,
        "created_at": timestamp,
        "session_status": "active",
        "model": BEDROCK_MODEL_ID,
        "metadata": metadata,
    }

    table.put_item(Item=item)
    logger.info(f"Saved assistant message: {message_id}")

    return message_id


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def lambda_handler(event, context: LambdaContext):
    """
    Worker Lambda triggered by SQS.
    Processes chat messages using Bedrock and saves responses.
    """
    logger.info("Worker Lambda triggered", extra={"event": event})

    try:
        # Process each SQS message
        for record in event["Records"]:
            message_body = json.loads(record["body"])

            user_id = message_body["user_id"]
            session_id = message_body["session_id"]
            message_id = message_body["message_id"]

            logger.info(f"Processing message: {message_id}")

            # 1. Fetch conversation history
            conversation_history = get_conversation_history(
                user_id, session_id, limit=20
            )
            logger.info(
                f"Fetched {len(conversation_history)} messages from history"
            )

            # 2. Build Bedrock messages
            bedrock_messages = build_bedrock_messages(conversation_history)

            # 3. Invoke Bedrock
            start_time = datetime.utcnow()
            bedrock_response = invoke_bedrock(bedrock_messages)
            end_time = datetime.utcnow()

            latency_ms = int((end_time - start_time).total_seconds() * 1000)

            # 4. Save assistant response
            metadata = {
                "latency_ms": latency_ms,
                "input_tokens": bedrock_response["usage"].get(
                    "input_tokens", 0
                ),
                "output_tokens": bedrock_response["usage"].get(
                    "output_tokens", 0
                ),
                "user_message_id": message_id,
            }

            assistant_message_id = save_assistant_message(
                user_id=user_id,
                session_id=session_id,
                content=bedrock_response["content"],
                metadata=metadata,
            )

            logger.info(
                f"Successfully processed message {message_id}, created assistant message {assistant_message_id}"
            )

        return {"statusCode": 200, "body": json.dumps({"status": "success"})}

    except Exception as e:
        logger.exception("Error processing SQS message")
        raise  # Let SQS handle retry logic
