FROM public.ecr.aws/lambda/python:3.11

# Install UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR ${LAMBDA_TASK_ROOT}

# Copy project files for dependency resolution
COPY pyproject.toml uv.lock* ./

# Export dependencies to requirements.txt and install
RUN uv export --no-hashes --frozen > requirements.txt && \
    uv pip install --system --no-cache -r requirements.txt

# Copy function code (changes more frequently)
COPY app.py ./

# Set the CMD to your handler
CMD [ "app.lambda_handler" ]
