from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.event_handler import APIGatewayRestResolver
from aws_lambda_powertools.logging import correlation_paths

logger = Logger()
tracer = Tracer()
app = APIGatewayRestResolver()


@app.get("/hello")
@tracer.capture_method
def hello():
    logger.info("Hello endpoint called")
    return {"message": "Hello World!", "status": "success"}


@app.get("/hello/<name>")
@tracer.capture_method
def hello_name(name):
    logger.info(f"Hello endpoint called with name: {name}")
    return {"message": f"Hello {name}!", "status": "success"}


@app.get("/health")
def health():
    return {"status": "healthy", "service": "lambda-api"}


@logger.inject_lambda_context(
    correlation_id_path=correlation_paths.API_GATEWAY_REST
)
@tracer.capture_lambda_handler
def lambda_handler(event, context):
    return app.resolve(event, context)
