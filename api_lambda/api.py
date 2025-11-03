import json
import os
import uuid
from datetime import datetime

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.event_handler import APIGatewayRestResolver
from aws_lambda_powertools.logging import correlation_paths
from boto3.dynamodb.conditions import Key

logger = Logger()
tracer = Tracer()
app = APIGatewayRestResolver()

# AWS Clients
dynamodb = boto3.resource("dynamodb")
sqs = boto3.client("sqs")

# Environment variables
DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]
SQS_QUEUE_URL = os.environ["SQS_QUEUE_URL"]

table = dynamodb.Table(DYNAMODB_TABLE)


@app.post("/chat")
@tracer.capture_method
def send_message():
    """
    Send a message to the chat system.
    Request body: {
        "user_id": "123",
        "session_id": "abc123",
        "content": "Hello, what's the weather?"
    }
    """
    try:
        body = app.current_event.json_body
        user_id = body.get("user_id")
        session_id = body.get("session_id")
        content = body.get("content")

        if not all([user_id, session_id, content]):
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {"error": "user_id, session_id, and content are required"}
                ),
            }

        # Generate message ID and timestamp
        message_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat() + "Z"

        # Composite keys
        pk = f"USER#{user_id}#SESSION#{session_id}"
        sk = timestamp

        # Save user message to DynamoDB
        item = {
            "PK": pk,
            "SK": sk,
            "message_id": message_id,
            "role": "user",
            "content": content,
            "created_at": timestamp,
            "session_status": "active",
            "metadata": {"tokens": len(content.split()), "source": "api"},
        }

        table.put_item(Item=item)
        logger.info(f"Saved user message: {message_id}")

        # Send message to SQS for processing
        sqs_message = {
            "user_id": user_id,
            "session_id": session_id,
            "message_id": message_id,
            "timestamp": timestamp,
        }

        sqs.send_message(
            QueueUrl=SQS_QUEUE_URL, MessageBody=json.dumps(sqs_message)
        )
        logger.info(f"Sent message to SQS: {message_id}")

        return {
            "statusCode": 202,
            "body": json.dumps(
                {
                    "message_id": message_id,
                    "status": "processing",
                    "timestamp": timestamp,
                }
            ),
        }

    except Exception as e:
        logger.exception("Error processing message")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


@app.get("/messages")
@tracer.capture_method
def get_messages():
    """
    Get conversation messages for a session.
    Query params: user_id, session_id, limit (optional, default 50)
    """
    try:
        user_id = app.current_event.get_query_string_value("user_id")
        session_id = app.current_event.get_query_string_value("session_id")
        limit = int(
            app.current_event.get_query_string_value(
                "limit", default_value="50"
            )
        )

        if not user_id or not session_id:
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {"error": "user_id and session_id are required"}
                ),
            }

        pk = f"USER#{user_id}#SESSION#{session_id}"

        # Query DynamoDB
        response = table.query(
            KeyConditionExpression=Key("PK").eq(pk),
            ScanIndexForward=False,  # Most recent first
            Limit=limit,
        )

        messages = response.get("Items", [])

        # Reverse to get chronological order
        messages.reverse()

        return {
            "statusCode": 200,
            "body": json.dumps(
                {"messages": messages, "count": len(messages)}, default=str
            ),
        }

    except Exception as e:
        logger.exception("Error fetching messages")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


@app.get("/sessions/<user_id>")
@tracer.capture_method
def get_user_sessions(user_id: str):
    """
    Get all sessions for a user (returns unique session IDs).
    """
    try:
        # This is a simple implementation - for production, consider using a GSI
        # or maintaining a separate sessions table
        response = table.query(
            IndexName="SessionStatusIndex",
            KeyConditionExpression=Key("session_status").eq("active"),
            FilterExpression="begins_with(PK, :user_prefix)",
            ExpressionAttributeValues={":user_prefix": f"USER#{user_id}#"},
        )

        # Extract unique session IDs
        sessions = set()
        for item in response.get("Items", []):
            pk = item["PK"]
            # Extract session_id from PK format: USER#123#SESSION#abc123
            session_id = (
                pk.split("#SESSION#")[1] if "#SESSION#" in pk else None
            )
            if session_id:
                sessions.add(session_id)

        return {
            "statusCode": 200,
            "body": json.dumps(
                {"user_id": user_id, "sessions": list(sessions)}
            ),
        }

    except Exception as e:
        logger.exception("Error fetching sessions")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


@app.get("/health")
def health():
    """Health check endpoint"""
    return {
        "statusCode": 200,
        "body": json.dumps({"status": "healthy", "service": "chat-api"}),
    }


@logger.inject_lambda_context(
    correlation_id_path=correlation_paths.API_GATEWAY_REST
)
@tracer.capture_lambda_handler
def lambda_handler(event, context):
    return app.resolve(event, context)
