```txt
Frontend
  ↓
API Gateway
  ↓
API Lambda (Non-container)
  ├── Save user message to DynamoDB
  └── Send message to SQS queue
        ↓
Worker Lambda (Container) ← SQS Trigger
  ├── Fetch conversation context from DynamoDB
  ├── Invoke Amazon Bedrock (Claude)
  ├── Save assistant reply to DynamoDB
  └── Process complete
        ↓
Frontend (Polling)
  └── GET /messages → Returns latest conversation
```

```sh
cd infra
```

```sh
terraform validate
```

```sh
terraform plan
```

```sh
terraform apply --auto-approve
```

```sh
API_URL=$(terraform output -raw api_endpoint)
```

```sh
API_URL=$(terraform output -raw api_endpoint)
uv run --with httpie http POST "$API_URL/chat" \
  user_id=333 \
  session_id=abc333 \
  content="How much is 3 + 3?"
```

```sh
API_URL=$(terraform output -raw api_endpoint)
uv run --with httpie http "$API_URL/messages" \
  user_id==333 \
  session_id==abc333 \
  limit==20
```

```sh
API_URL=$(terraform output -raw api_endpoint)
uv run --with httpie http "$API_URL/sessions/123"
```

```sh
API_URL=$(terraform output -raw api_endpoint)
uv run --with httpie http "$API_URL/health"
```
