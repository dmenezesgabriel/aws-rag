import json
import os
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Union

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext
from boto3.dynamodb.conditions import Key
from boto3.resources.base import ServiceResource
from botocore.client import BaseClient
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field

logger: Logger = Logger()

DYNAMODB_TABLE: str = os.environ["DYNAMODB_TABLE"]
LLM_PROVIDER_STRATEGY: str = os.environ.get(
    "LLM_PROVIDER_STRATEGY", "LangchainLLMAmazonNovaLiteStrategy"
)
BEDROCK_MODEL_ID: str = os.environ.get(
    "BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0"
)

dynamodb_resource: ServiceResource = boto3.resource("dynamodb")
bedrock_client: BaseClient = boto3.client("bedrock-runtime")


class Message(BaseModel):
    PK: str
    SK: str
    message_id: str
    role: str
    content: Union[str, Dict[str, Union[str, int]]]
    created_at: str
    session_status: str
    model: Union[str, None] = None
    metadata: Dict[str, Any]


class LLMUsage(BaseModel):
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)


class LLMResponse(BaseModel):
    content: Union[str, List[Union[str, Dict[Any, Any]]]]
    usage: LLMUsage


class WorkerMessageBody(BaseModel):
    user_id: str
    session_id: str
    message_id: str


class AssistantMetadata(BaseModel):
    latency_ms: int
    input_tokens: int
    output_tokens: int
    user_message_id: str


class LLMInputMessage(BaseModel):
    role: str
    content: str


class DynamoDBRepository:
    def __init__(self, table_name: str, dynamodb_resource: Any):
        self.table: Any = dynamodb_resource.Table(table_name)
        logger.info(f"DynamoDBRepository initialized for table: {table_name}")

    def get_conversation_history(
        self, user_id: str, session_id: str, limit: int = 10
    ) -> List[Message]:
        pk: str = f"USER#{user_id}#SESSION#{session_id}"
        response: Dict[str, Any] = self.table.query(
            KeyConditionExpression=Key("PK").eq(pk),
            ScanIndexForward=False,
            Limit=limit,
        )
        messages: List[Message] = [
            Message.model_validate(item) for item in response.get("Items", [])
        ]
        messages.reverse()
        return messages

    def save_assistant_message(
        self,
        user_id: str,
        session_id: str,
        content: Union[str, List[Union[str, Dict[Any, Any]]]],
        metadata: AssistantMetadata,
    ) -> str:
        message_id: str = str(uuid.uuid4())
        timestamp: str = (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )

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
            "metadata": metadata.model_dump(),
        }

        self.table.put_item(Item=item)
        logger.info(f"Saved assistant message: {message_id}")

        return message_id


class LLMProviderStrategy(ABC):
    def __init__(self, model_id: str, client: BaseClient):
        self.model_id = model_id
        self.client = client
        self.region_name = self.client.meta.region_name

    @abstractmethod
    def invoke_llm(self, messages: List[LLMInputMessage]) -> LLMResponse:
        raise NotImplementedError


class LangchainLLMAmazonNovaLiteStrategy(LLMProviderStrategy):
    def invoke_llm(self, messages: List[LLMInputMessage]) -> LLMResponse:
        logger.info(f"LangChain Strategy: Invoking model {self.model_id}")

        try:
            chat = ChatBedrockConverse(
                model=self.model_id,
                client=self.client,
                region_name=self.region_name,
            )

            langchain_messages: List[Union[HumanMessage, AIMessage]] = []
            for msg in messages:
                role: str = msg.role
                content: str = msg.content
                if role == "user":
                    langchain_messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    langchain_messages.append(AIMessage(content=content))

            response: AIMessage = chat.invoke(langchain_messages)

            assistant_message: Union[str, List[Union[str, Dict[Any, Any]]]] = (
                response.content
            )
            usage_metadata: Dict[str, int] = response.response_metadata.get(
                "usage", {}
            )

            usage: LLMUsage = LLMUsage(
                input_tokens=usage_metadata.get("input_token_count", 0),
                output_tokens=usage_metadata.get("output_token_count", 0),
            )

            return LLMResponse(content=assistant_message, usage=usage)

        except Exception as e:
            logger.exception("Error invoking Bedrock via LangChain")
            raise


class LLMProviderFactory:
    def __init__(self, model_id: str, client: BaseClient):
        self.model_id: str = model_id
        self.client: BaseClient = client
        self.strategies: Dict[str, type[LLMProviderStrategy]] = {
            "LangchainLLMAmazonNovaLiteStrategy": LangchainLLMAmazonNovaLiteStrategy,
        }

    def get_strategy(self, strategy_name: str) -> LLMProviderStrategy:
        strategy_class = self.strategies.get(strategy_name)
        if not strategy_class:
            raise ValueError(f"Unknown LLM strategy: {strategy_name}")

        return strategy_class(self.model_id, self.client)


class LLMProvider:
    def __init__(self, strategy: LLMProviderStrategy):
        self.strategy: LLMProviderStrategy = strategy

    @staticmethod
    def build_bedrock_messages(
        conversation_history: List[Message],
    ) -> List[LLMInputMessage]:
        messages: List[LLMInputMessage] = []
        for msg in conversation_history:
            content: Union[str, Dict[str, Union[str, int]]] = msg.content
            if not isinstance(content, str):
                content = json.dumps(content)

            messages.append(LLMInputMessage(role=msg.role, content=content))
        return messages

    def invoke_llm(self, messages: List[LLMInputMessage]) -> LLMResponse:
        return self.strategy.invoke_llm(messages)


class Worker:
    def __init__(
        self,
        dynamodb_repository: DynamoDBRepository,
        llm_provider: LLMProvider,
    ):
        self.dynamodb_repository: DynamoDBRepository = dynamodb_repository
        self.llm_provider: LLMProvider = llm_provider

    def process_record(self, message_body: WorkerMessageBody) -> None:
        user_id: str = message_body.user_id
        session_id: str = message_body.session_id
        user_message_id: str = message_body.message_id

        logger.info(f"Processing message: {user_message_id}")

        conversation_history: List[Message] = (
            self.dynamodb_repository.get_conversation_history(
                user_id, session_id, limit=20
            )
        )
        logger.info(
            f"Fetched {len(conversation_history)} messages from history"
        )

        llm_messages: List[LLMInputMessage] = (
            self.llm_provider.build_bedrock_messages(conversation_history)
        )

        start_time: datetime = datetime.now(timezone.utc)
        llm_response: LLMResponse = self.llm_provider.invoke_llm(llm_messages)
        end_time: datetime = datetime.now(timezone.utc)

        latency_ms: int = int((end_time - start_time).total_seconds() * 1000)

        usage_metrics: LLMUsage = llm_response.usage

        metadata: AssistantMetadata = AssistantMetadata(
            latency_ms=latency_ms,
            input_tokens=usage_metrics.input_tokens,
            output_tokens=usage_metrics.output_tokens,
            user_message_id=user_message_id,
        )

        assistant_message_id: str = (
            self.dynamodb_repository.save_assistant_message(
                user_id=user_id,
                session_id=session_id,
                content=llm_response.content,
                metadata=metadata,
            )
        )

        logger.info(
            f"Successfully processed message {user_message_id}, created assistant message {assistant_message_id}"
        )


dynamodb_repository: DynamoDBRepository = DynamoDBRepository(
    DYNAMODB_TABLE, dynamodb_resource
)

strategy: LLMProviderStrategy = LLMProviderFactory(
    BEDROCK_MODEL_ID, bedrock_client
).get_strategy(LLM_PROVIDER_STRATEGY)

llm_provider: LLMProvider = LLMProvider(strategy)

worker: Worker = Worker(dynamodb_repository, llm_provider)


@logger.inject_lambda_context
def lambda_handler(
    event: Dict[str, Any], context: LambdaContext
) -> Dict[str, Any]:
    logger.info("Worker Lambda triggered", extra={"event": event})

    try:
        for record in event.get("Records", []):
            message_body: WorkerMessageBody = WorkerMessageBody.parse_raw(
                record["body"]
            )
            worker.process_record(message_body)

        return {"statusCode": 200, "body": json.dumps({"status": "success"})}

    except Exception as e:
        logger.exception("Error processing SQS message batch")
        raise
