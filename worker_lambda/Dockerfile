FROM public.ecr.aws/lambda/python:3.12

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR ${LAMBDA_TASK_ROOT}

COPY pyproject.toml uv.lock* ./

RUN uv export --no-hashes --frozen > requirements.txt
RUN uv pip install --system --no-cache -r requirements.txt

COPY worker.py ${LAMBDA_TASK_ROOT}/

CMD [ "worker.lambda_handler" ]
