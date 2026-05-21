# API Specification

Base URL for local testing: `http://127.0.0.1:8000`

## `POST /documents`

Uploads one PDF, Python, text, or Markdown file as `multipart/form-data`.

Request field:

| Field | Type | Required |
|---|---|---|
| `file` | file | yes |

Response `202`:

```json
{
  "document_id": "uuid",
  "filename": "Knowledge_Base_Sample (2).pdf",
  "file_type": "pdf",
  "status": "processing"
}
```

The file is stored locally and ingestion continues with FastAPI background processing.

## `GET /documents/{document_id}`

Returns ingestion status for one uploaded document.

Response `200`:

```json
{
  "document_id": "uuid",
  "filename": "Source_Code_Sample (2).py",
  "file_type": "py",
  "status": "ready",
  "chunk_count": 8,
  "deleted": false,
  "error": null,
  "created_at": "2026-05-21T09:00:00+00:00"
}
```

`status` is `processing`, `ready`, `failed`, `deleted`, or `delete_failed`.

## `POST /query`

Embeds a natural-language query and returns ranked chunks from Chroma.

Request:

```json
{
  "query": "What happens when report_failure is called?",
  "top_k": 5,
  "filters": {
    "file_type": "py",
    "document_id": "uuid"
  }
}
```

Both filters are optional.

Response `200`:

```json
{
  "query": "What happens when report_failure is called?",
  "top_k": 5,
  "latency_ms": 124,
  "results": [
    {
      "rank": 1,
      "score": 0.82,
      "content": "def report_failure(self, proxy): ...",
      "document_id": "uuid",
      "filename": "Source_Code_Sample (2).py",
      "file_type": "py",
      "metadata": {
        "document_id": "uuid",
        "filename": "Source_Code_Sample (2).py",
        "file_type": "py",
        "chunk_index": 3,
        "is_deleted": false
      }
    }
  ]
}
```

The endpoint returns retrieved chunks only. It does not call a chat model to generate an answer.

## `DELETE /documents/{document_id}`

Soft delete is the default:

```text
DELETE /documents/{document_id}
```

Response:

```json
{
  "document_id": "uuid",
  "status": "soft_deleted",
  "deleted_at": "2026-05-21T09:15:00+00:00"
}
```

Hard delete removes Chroma records before SQLite metadata:

```text
DELETE /documents/{document_id}?hard=true
```

If hard delete fails, metadata is kept and status becomes `delete_failed`.

## `GET /health`

Response:

```json
{
  "status": "ok"
}
```
