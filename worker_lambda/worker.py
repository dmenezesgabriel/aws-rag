import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import boto3  # type: ignore
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from boto3.dynamodb.conditions import Key  # type: ignore

logger: Logger = Logger()


DYNAMODB_TABLE: str = os.environ["DYNAMODB_TABLE"]
BEDROCK_MODEL_ID: str = os.environ.get(
    "BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0"
)


dynamodb_resource: Any = boto3.resource("dynamodb")
bedrock_runtime: Any = boto3.client("bedrock-runtime")


class DynamoDBRepository:

    def __init__(self, table_name: str, dynamodb_resource: Any):
        self.table: Any = dynamodb_resource.Table(table_name)
        logger.info(f"DynamoDBRepository initialized for table: {table_name}")

    def get_conversation_history(
        self, user_id: str, session_id: str, limit: int = 10
    ) -> List[Dict[str, Any]]:

        pk: str = f"USER#{user_id}#SESSION#{session_id}"

        response: Dict[str, Any] = self.table.query(
            KeyConditionExpression=Key("PK").eq(pk),
            ScanIndexForward=False,  # Most recent first
            Limit=limit,
        )

        messages: List[Dict[str, Any]] = response.get("Items", [])
        messages.reverse()  # Chronological order
        return messages

    def save_assistant_message(
        self,
        user_id: str,
        session_id: str,
        content: Union[str, Dict[str, int]],
        metadata: Dict[str, Any],
    ) -> str:

        message_id: str = str(uuid.uuid4())
        timestamp: str = datetime.utcnow().isoformat() + "Z"

        pk: str = f"USER#{user_id}#SESSION#{session_id}"
        sk: str = timestamp

        item: Dict[str, Any] = {
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

        self.table.put_item(Item=item)
        logger.info(f"Saved assistant message: {message_id}")

        return message_id


class BedrockService:

    def __init__(self, bedrock_client: Any, model_id: str):
        self.bedrock_runtime: Any = bedrock_client
        self.model_id: str = model_id

    @staticmethod
    def build_bedrock_messages(
        conversation_history: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:

        messages: List[Dict[str, str]] = []

        for msg in conversation_history:
            # Bedrock API uses "user" and "assistant" roles
            messages.append({"role": msg["role"], "content": msg["content"]})

        return messages

    def invoke_bedrock(
        self, messages: List[Dict[str, Any]]
    ) -> Dict[str, Union[str, Dict[str, int]]]:
        try:
            request_body: Dict[str, Any] = {
                "messages": messages,
            }

            logger.info(f"Invoking Bedrock model: {self.model_id}")

            response: Dict[str, Any] = self.bedrock_runtime.invoke_model(
                modelId=self.model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(request_body),
            )

            response_body: Dict[str, Any] = json.loads(response["body"].read())

            assistant_message: str = response_body["content"][0]["text"]
            usage: Dict[str, int] = response_body.get("usage", {})

            return {"content": assistant_message, "usage": usage}

        except Exception as e:
            logger.exception("Error invoking Bedrock")
            raise  # Re-raise the exception for SQS retry


class Worker:

    def __init__(
        self,
        ddb_repo: DynamoDBRepository,
        bedrock_service: BedrockService,
    ):
        self.ddb_repo: DynamoDBRepository = ddb_repo
        self.bedrock_service: BedrockService = bedrock_service

    def process_record(self, message_body: Dict[str, str]) -> None:
        user_id: str = message_body["user_id"]
        session_id: str = message_body["session_id"]
        user_message_id: str = message_body["message_id"]

        logger.info(f"Processing message: {user_message_id}")

        conversation_history: List[Dict[str, Any]] = (
            self.ddb_repo.get_conversation_history(
                user_id, session_id, limit=20
            )
        )
        logger.info(
            f"Fetched {len(conversation_history)} messages from history"
        )

        bedrock_messages: List[Dict[str, Any]] = (
            self.bedrock_service.build_bedrock_messages(conversation_history)
        )

        start_time: datetime = datetime.utcnow()
        bedrock_response: Dict[str, Union[str, Dict[str, int]]] = (
            self.bedrock_service.invoke_bedrock(bedrock_messages)
        )
        end_time: datetime = datetime.utcnow()

        latency_ms: int = int((end_time - start_time).total_seconds() * 1000)

        usage_metrics: Dict[str, int] = (
            bedrock_response["usage"]
            if isinstance(bedrock_response["usage"], dict)
            else {}
        )

        metadata: Dict[str, Union[int, str]] = {
            "latency_ms": latency_ms,
            "input_tokens": usage_metrics.get("input_tokens", 0),
            "output_tokens": usage_metrics.get("output_tokens", 0),
            "user_message_id": user_message_id,
        }

        assistant_message_id: str = self.ddb_repo.save_assistant_message(
            user_id=user_id,
            session_id=session_id,
            content=bedrock_response["content"],
            metadata=metadata,
        )

        logger.info(
            f"Successfully processed message {user_message_id}, created assistant message {assistant_message_id}"
        )


ddb_repo: DynamoDBRepository = DynamoDBRepository(
    DYNAMODB_TABLE, dynamodb_resource
)
bedrock_service: BedrockService = BedrockService(
    bedrock_runtime, BEDROCK_MODEL_ID
)
worker: Worker = Worker(ddb_repo, bedrock_service)


@logger.inject_lambda_context
def lambda_handler(
    event: Dict[str, Any], context: LambdaContext
) -> Dict[str, Any]:
    logger.info("Worker Lambda triggered", extra={"event": event})

    try:
        for record in event.get("Records", []):
            message_body: Dict[str, str] = json.loads(record["body"])
            worker.process_record(message_body)

        return {"statusCode": 200, "body": json.dumps({"status": "success"})}

    except Exception as e:
        logger.exception("Error processing SQS message batch")
        # By raising an exception, SQS will handle the retry logic.
        raise
