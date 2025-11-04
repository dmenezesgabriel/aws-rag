import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Union

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayRestResolver
from aws_lambda_powertools.logging import correlation_paths
from aws_lambda_powertools.utilities.typing import LambdaContext
from boto3.dynamodb.conditions import Key

logger: Logger = Logger()
app: APIGatewayRestResolver = APIGatewayRestResolver()

DYNAMODB_TABLE: str = os.environ["DYNAMODB_TABLE"]
SQS_QUEUE_URL: str = os.environ["SQS_QUEUE_URL"]

dynamodb_resource = boto3.resource("dynamodb")
sqs_client = boto3.client("sqs")


class DynamoDBRepository:

    def __init__(self, table_name: str, dynamodb_resource: Any):
        self.table: Any = dynamodb_resource.Table(table_name)
        logger.info(f"DynamoDBRepository initialized for table: {table_name}")

    def put_item(self, item: Dict[str, Any]) -> None:
        self.table.put_item(Item=item)

    def query_messages(
        self, user_id: str, session_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        pk: str = f"USER#{user_id}#SESSION#{session_id}"

        response: Dict[str, Any] = self.table.query(
            KeyConditionExpression=Key("PK").eq(pk),
            ScanIndexForward=False,  # Most recent first
            Limit=limit,
        )

        messages: List[Dict[str, Any]] = response.get("Items", [])
        messages.reverse()
        return messages

    def get_user_sessions(self, user_id: str) -> List[str]:
        response: Dict[str, Any] = self.table.query(
            IndexName="SessionStatusIndex",
            KeyConditionExpression=Key("session_status").eq("active"),
            FilterExpression="begins_with(PK, :user_prefix)",
            ExpressionAttributeValues={":user_prefix": f"USER#{user_id}#"},
        )

        sessions: Set[str] = set()
        for item in response.get("Items", []):
            pk: str = item["PK"]
            session_id: Optional[str] = (
                pk.split("#SESSION#")[1] if "#SESSION#" in pk else None
            )
            if session_id:
                sessions.add(session_id)

        return list(sessions)


class SQSRepository:
    def __init__(self, queue_url: str, sqs_client: Any):
        self.queue_url: str = queue_url
        self.sqs_client: Any = sqs_client

    def send_message(self, message_body: Dict[str, Any]) -> None:
        """Sends a JSON message to the SQS queue."""
        self.sqs_client.send_message(
            QueueUrl=self.queue_url, MessageBody=json.dumps(message_body)
        )


class ChatService:
    def __init__(self, ddb_repo: DynamoDBRepository, sqs_repo: SQSRepository):
        self.ddb_repo: DynamoDBRepository = ddb_repo
        self.sqs_repo: SQSRepository = sqs_repo

    def send_message(self, body: Dict[str, str]) -> Dict[str, Any]:
        user_id: Optional[str] = body.get("user_id")
        session_id: Optional[str] = body.get("session_id")
        content: Optional[str] = body.get("content")

        if not all([user_id, session_id, content]):
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {"error": "user_id, session_id, and content are required"}
                ),
            }

        message_id: str = str(uuid.uuid4())
        timestamp: str = datetime.now().isoformat() + "Z"

        pk: str = f"USER#{user_id}#SESSION#{session_id}"
        sk: str = timestamp

        item: Dict[str, Any] = {
            "PK": pk,
            "SK": sk,
            "message_id": message_id,
            "role": "user",
            "content": content,
            "created_at": timestamp,
            "session_status": "active",
            "metadata": {
                "tokens": len(content.split() if content else ""),
                "source": "api",
            },
        }
        self.ddb_repo.put_item(item)
        logger.info(f"Saved user message: {message_id}")

        sqs_message: Dict[str, Optional[str]] = {
            "user_id": user_id,
            "session_id": session_id,
            "message_id": message_id,
            "timestamp": timestamp,
        }
        self.sqs_repo.send_message(sqs_message)
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

    def get_messages(self, query_params: Dict[str, Any]) -> Dict[str, Any]:
        user_id: Optional[str] = query_params.get("user_id")
        session_id: Optional[str] = query_params.get("session_id")
        limit: int = int(query_params.get("limit", 50))

        if not user_id or not session_id:
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {"error": "user_id and session_id are required"}
                ),
            }

        messages: List[Dict[str, Any]] = self.ddb_repo.query_messages(
            user_id, session_id, limit
        )

        return {
            "statusCode": 200,
            "body": json.dumps(
                {"messages": messages, "count": len(messages)}, default=str
            ),
        }

    def get_user_sessions(self, user_id: str) -> Dict[str, Any]:
        sessions: List[str] = self.ddb_repo.get_user_sessions(user_id)

        return {
            "statusCode": 200,
            "body": json.dumps({"user_id": user_id, "sessions": sessions}),
        }


ddb_repo: DynamoDBRepository = DynamoDBRepository(
    DYNAMODB_TABLE, dynamodb_resource
)
sqs_repo: SQSRepository = SQSRepository(SQS_QUEUE_URL, sqs_client)
chat_service: ChatService = ChatService(ddb_repo, sqs_repo)


@app.post("/chat")
def post_chat_message() -> Dict[str, Any]:
    try:
        body: Dict[str, str] = app.current_event.json_body
        return chat_service.send_message(body)
    except Exception as e:
        logger.exception("Error processing message in route")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


@app.get("/messages")
def get_conversation_messages() -> Dict[str, Any]:
    try:
        query_params: Dict[str, Optional[str]] = {
            "user_id": app.current_event.get_query_string_value("user_id"),
            "session_id": app.current_event.get_query_string_value(
                "session_id"
            ),
            "limit": app.current_event.get_query_string_value(
                "limit", default_value="50"
            ),
        }
        return chat_service.get_messages(query_params)
    except Exception as e:
        logger.exception("Error fetching messages in route")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


@app.get("/sessions/<user_id>")
def get_sessions(user_id: str) -> Dict[str, Any]:
    try:
        return chat_service.get_user_sessions(user_id)
    except Exception as e:
        logger.exception("Error fetching sessions in route")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "statusCode": 200,
        "body": json.dumps({"status": "healthy", "service": "chat-api"}),
    }


@logger.inject_lambda_context(
    correlation_id_path=correlation_paths.API_GATEWAY_REST
)
def lambda_handler(
    event: Dict[str, Any], context: LambdaContext
) -> Dict[str, Any]:
    return app.resolve(event, context)
