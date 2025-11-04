# /// script
# dependencies = ["diagrams"]
# ///
from diagrams import Cluster, Diagram
from diagrams.aws.compute import Lambda
from diagrams.aws.database import Dynamodb
from diagrams.aws.general import Client
from diagrams.aws.integration import SimpleQueueServiceSqsQueue as SQS
from diagrams.aws.ml import Bedrock
from diagrams.aws.network import APIGateway

with Diagram(
    "Serverless AI Chat Architecture",
    show=False,
    filename="assets/serverless_chat",
    direction="LR",  # Left-to-right flow
):
    frontend = Client("Frontend")
    api_gateway = APIGateway("API Gateway")
    dynamodb = Dynamodb("DynamoDB")

    with Cluster("API Ingestion"):
        api_lambda = Lambda("API Lambda\n(Non-container)")
        sqs = SQS("SQS Queue")

    with Cluster("Asynchronous Processing"):
        worker_lambda = Lambda("Worker Lambda\n(Container)")
        bedrock = Bedrock("Amazon Bedrock")

    # Flow (single arrows only)
    frontend >> api_gateway >> api_lambda >> sqs >> worker_lambda >> bedrock
    api_lambda >> dynamodb
    worker_lambda >> dynamodb
