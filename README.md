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
curl -X POST $API_URL/chat \
  -H "Content-Type: application/json" \
  -d '{"user_id":"222","session_id":"abc222","content":"Hello! What is your name?"}'
```

```sh
curl "$API_URL/messages?user_id=222&session_id=abc222&limit=20"
```

```sh
curl "$API_URL/sessions/123"
```

```sh
curl "$API_URL/health"
```
