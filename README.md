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
curl $API_URL/hello
```

```sh
curl $API_URL/hello/Alice
```

```sh
curl $API_URL/health
```
