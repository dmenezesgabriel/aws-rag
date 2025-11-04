import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Union

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayRestResolver
from aws_lambda_powertools.event_handler.api_gateway import CORSConfig
from aws_lambda_powertools.logging import correlation_paths
from aws_lambda_powertools.utilities.typing import LambdaContext
from boto3.dynamodb.conditions import Key
from pydantic import BaseModel, Field

cors_config = CORSConfig(
    allow_origin="*",
    allow_headers=["Content-Type", "Authorization"],
    expose_headers=["Content-Type"],
    max_age=300,
)

logger: Logger = Logger()
app: APIGatewayRestResolver = APIGatewayRestResolver(cors=cors_config)

DYNAMODB_TABLE: str = os.environ["DYNAMODB_TABLE"]
SQS_QUEUE_URL: str = os.environ["SQS_QUEUE_URL"]

dynamodb_resource = boto3.resource("dynamodb")
sqs_client = boto3.client("sqs")


class MessageMetadata(BaseModel):
    tokens: int = Field(default=0)
    source: str = Field(default="api")


class MessageInDB(BaseModel):
    PK: str
    SK: str
    message_id: str
    role: str
    content: Union[str, Dict[str, Union[str, int]]]
    created_at: str
    session_status: str
    model: Optional[str] = None
    metadata: MessageMetadata


class SendMessageRequest(BaseModel):
    user_id: str
    session_id: str
    content: str


class GetMessagesQueryParams(BaseModel):
    user_id: str
    session_id: str
    limit: int = Field(default=50, ge=1, le=100)


class MessageSentResponse(BaseModel):
    message_id: str
    status: str = "processing"
    timestamp: str


class ConversationResponse(BaseModel):
    messages: List[MessageInDB]
    count: int


class UserSessionResponse(BaseModel):
    user_id: str
    sessions: List[str]


class DynamoDBRepository:
    def __init__(self, table_name: str, dynamodb_resource: Any):
        self.table: Any = dynamodb_resource.Table(table_name)
        logger.info(f"DynamoDBRepository initialized for table: {table_name}")

    def put_item(self, item: Dict[str, Any]) -> None:
        self.table.put_item(Item=item)

    def query_messages(
        self, user_id: str, session_id: str, limit: int = 50
    ) -> List[MessageInDB]:
        pk: str = f"USER#{user_id}#SESSION#{session_id}"

        response: Dict[str, Any] = self.table.query(
            KeyConditionExpression=Key("PK").eq(pk),
            ScanIndexForward=False,
            Limit=limit,
        )

        messages_raw: List[Dict[str, Any]] = response.get("Items", [])
        messages: List[MessageInDB] = [
            MessageInDB.model_validate(item) for item in messages_raw
        ]
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
            try:
                session_id: str = pk.split("#SESSION#")[1]
                sessions.add(session_id)
            except IndexError:
                logger.warning(
                    f"PK format incorrect for session extraction: {pk}"
                )

        return list(sessions)


class SQSRepository:
    def __init__(self, queue_url: str, sqs_client: Any):
        self.queue_url: str = queue_url
        self.sqs_client: Any = sqs_client

    def send_message(self, message_body: Dict[str, Any]) -> None:
        self.sqs_client.send_message(
            QueueUrl=self.queue_url, MessageBody=json.dumps(message_body)
        )


class ChatService:
    def __init__(
        self,
        dynamodb_repository: DynamoDBRepository,
        sqs_repository: SQSRepository,
    ):
        self.dynamodb_repository: DynamoDBRepository = dynamodb_repository
        self.sqs_repository: SQSRepository = sqs_repository

    def send_message(self, body: SendMessageRequest) -> MessageSentResponse:
        user_id: str = body.user_id
        session_id: str = body.session_id
        content: str = body.content

        message_id: str = str(uuid.uuid4())
        timestamp: str = (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )

        pk: str = f"USER#{user_id}#SESSION#{session_id}"
        sk: str = timestamp

        token_count: int = len(content.split())

        item_data = {
            "PK": pk,
            "SK": sk,
            "message_id": message_id,
            "role": "user",
            "content": content,
            "created_at": timestamp,
            "session_status": "active",
            "metadata": MessageMetadata(tokens=token_count).model_dump(),
        }

        MessageInDB.model_validate(item_data)
        self.dynamodb_repository.put_item(item_data)
        logger.info(f"Saved user message: {message_id}")

        sqs_message: Dict[str, str] = {
            "user_id": user_id,
            "session_id": session_id,
            "message_id": message_id,
        }
        self.sqs_repository.send_message(sqs_message)
        logger.info(f"Sent message to SQS: {message_id}")

        return MessageSentResponse(message_id=message_id, timestamp=timestamp)

    def get_messages(
        self, query_params: GetMessagesQueryParams
    ) -> ConversationResponse:
        messages: List[MessageInDB] = self.dynamodb_repository.query_messages(
            query_params.user_id, query_params.session_id, query_params.limit
        )

        return ConversationResponse(messages=messages, count=len(messages))

    def get_user_sessions(self, user_id: str) -> UserSessionResponse:
        sessions: List[str] = self.dynamodb_repository.get_user_sessions(
            user_id
        )
        return UserSessionResponse(user_id=user_id, sessions=sessions)


dynamodb_repository: DynamoDBRepository = DynamoDBRepository(
    DYNAMODB_TABLE, dynamodb_resource
)
sqs_repository: SQSRepository = SQSRepository(SQS_QUEUE_URL, sqs_client)
chat_service: ChatService = ChatService(dynamodb_repository, sqs_repository)


@app.post("/chat")
def post_chat_message() -> Dict[str, Any]:
    try:
        body: SendMessageRequest = SendMessageRequest.model_validate(
            app.current_event.json_body
        )
        response_model: MessageSentResponse = chat_service.send_message(body)

        return {
            "statusCode": 202,
            "body": response_model.model_dump_json(),
        }
    except Exception as e:
        logger.exception("Error processing message in route")
        error_message = (
            str(e) if isinstance(e, ValueError) else "Internal Server Error"
        )
        return {
            "statusCode": 500,
            "body": json.dumps({"error": error_message}),
        }


@app.get("/messages")
def get_conversation_messages() -> Dict[str, Any]:
    try:
        query_params_raw: Dict[str, Any] = {
            "user_id": app.current_event.get_query_string_value("user_id"),
            "session_id": app.current_event.get_query_string_value(
                "session_id"
            ),
            "limit": app.current_event.get_query_string_value(
                "limit", default_value="50"
            ),
        }
        query_params: GetMessagesQueryParams = (
            GetMessagesQueryParams.model_validate(query_params_raw)
        )

        response_model: ConversationResponse = chat_service.get_messages(
            query_params
        )

        return {
            "statusCode": 200,
            "body": response_model.model_dump_json(by_alias=True),
        }
    except Exception as e:
        logger.exception("Error fetching messages in route")
        error_message = (
            str(e) if isinstance(e, ValueError) else "Internal Server Error"
        )
        return {
            "statusCode": 500,
            "body": json.dumps({"error": error_message}),
        }


@app.get("/sessions/<user_id>")
def get_sessions(user_id: str) -> Dict[str, Any]:
    try:
        response_model: UserSessionResponse = chat_service.get_user_sessions(
            user_id
        )

        return {
            "statusCode": 200,
            "body": response_model.model_dump_json(),
        }
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
