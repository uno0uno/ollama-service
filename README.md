# Ollama Extract API

REST API built with FastAPI that exposes a local LLM model (via Ollama) for structured data extraction from free-form text.

## What it does

- Receives unstructured text (invoices, letters, documents)
- Processes it with a small LLM model (qwen2.5:0.5b)
- Returns structured JSON based on a schema you define
- Authentication via shared API keys from the WARO ecosystem (`waro_sk_xxx`)

## Endpoints

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| GET | `/health` | No | Health check |
| POST | `/extract` | Yes | Extract data from text and return structured JSON |
| POST | `/chat` | Yes | Free chat with the model |

## Requirements

- Docker and Docker Compose
- Access to the WARO PostgreSQL database (`api_tokens` table)

## Setup

1. Configure environment variables:

```bash
cp .env.example .env
# Edit .env with your credentials
```

2. Start services:

```bash
docker compose up -d
```

3. First run downloads the model (~400MB). Verify with:

```bash
curl http://localhost:8100/health
```

## Usage

### Extract data from a document

```bash
curl http://localhost:8100/extract \
  -H "Authorization: Bearer waro_sk_your_key" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Invoice #1234. Client: John Doe. Total: $150.00",
    "schema_json": {
      "invoice_number": "string",
      "client": "string",
      "total": "number"
    }
  }'
```

### Free chat

```bash
curl http://localhost:8100/chat \
  -H "Authorization: Bearer waro_sk_your_key" \
  -H "Content-Type: application/json" \
  -d '{"message": "Summarize this text: ..."}'
```

## Stack

- **Ollama** - LLM model server
- **qwen2.5:0.5b** - Model (~400MB RAM)
- **FastAPI** - REST API
- **asyncpg** - PostgreSQL connection for auth
