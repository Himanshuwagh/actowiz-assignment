# API Specification

**Base URL:** `https://api.internal.company.com/v1`  
**Auth:** `X-API-Key` header on every request

---

## Error format (consistent across all endpoints)

```json
{
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "No document with that id",
    "request_id": "uuid"
  }
}
```

Common codes: `400` bad request, `401` auth, `404` not found, `409` duplicate, `413` too large, `422` unsupported type, `429` rate limit, `500` server error.

---

## POST /documents — Upload a file

Ingestion is async. Returns immediately, processing happens in background.

**Request:** `multipart/form-data`

| Field | Required | Notes |
|---|---|---|
| `file` | ✅ | PDF, markdown, txt, or code file (`.py`, `.js`, `.ts`, etc.) |
| `tags` | No | JSON array, e.g. `["rag", "internal"]` |
| `description` | No | Free text |

Max size: 50 MB.

**Response `202`:**
```json
{
  "document_id": "uuid",
  "job_id": "uuid",
  "filename": "Knowledge_Base_Sample.pdf",
  "status": "pending",
  "created_at": "2026-05-21T10:00:00Z"
}
```

**What happens in the background:**
1. Extract text (PDF → `pdfminer`, code → raw read + AST parse)
2. SHA-256 dedup check
3. Chunk the content
4. Embed chunks via OpenAI (batched)
5. Store vectors in Qdrant, metadata in Postgres
6. Set status to `ready`

Status flow: `pending → processing → ready` (or `failed`)

**Errors:** `409` if same file already uploaded, `422` if file type not supported.

---

## POST /query — Semantic search

**Request body:**
```json
{
  "query": "How does the proxy rotator handle failed proxies?",
  "top_k": 5,
  "filters": {
    "file_type": "py",
    "document_ids": ["uuid-of-source-code-sample"]
  },
  "rerank": true
}
```

`top_k` defaults to 5, `rerank` defaults to true.

**Filters available:** `file_type`, `tags`, `document_ids`, `created_after`, `created_before`.

**Response `200`:**
```json
{
  "query": "How does the proxy rotator handle failed proxies?",
  "results": [
    {
      "rank": 1,
      "score": 0.93,
      "chunk_id": "uuid",
      "document_name": "Source_Code_Sample.py",
      "file_type": "py",
      "content": "def report_failure(self, proxy):\n    stats['score'] = 0\n    stats['penalty_factor'] += self.penalty_increment\n    stats['last_used'] = time.time()",
      "metadata": { "class_name": "DecayProxyRotator", "function_name": "report_failure", "start_line": 57 }
    }
  ],
  "total_results": 5,
  "latency_ms": 145,
  "rerank_applied": true
}
```

**Internal flow:** embed query → Qdrant ANN search (top\_k × 3 candidates) → payload filter → cross-encoder rerank → return top\_k.

---

## DELETE /documents/{id}

**Soft delete (default):** sets `deleted_at`, excludes from search via Qdrant payload flag. Fast (<5ms).

**Hard delete (`?hard=true`):** deletes Qdrant vectors + Postgres rows. Uses saga pattern to handle partial failures — each step retried independently via Celery.

**Response:**
```json
{
  "document_id": "uuid",
  "status": "soft_deleted",
  "deleted_at": "2026-05-21T11:00:00Z"
}
```

---

## GET /documents — List documents

```
GET /documents?file_type=pdf&status=ready&page=1&limit=20
```

**Response:**
```json
{
  "documents": [
    { "document_id": "uuid", "filename": "Knowledge_Base_Sample.pdf", "file_type": "pdf", "status": "ready", "chunk_count": 94 },
    { "document_id": "uuid", "filename": "Source_Code_Sample.py",    "file_type": "py",  "status": "ready", "chunk_count": 12 }
  ],
  "total": 2
}
```

---

## GET /jobs/{id} — Poll ingestion status

```json
{
  "job_id": "uuid",
  "status": "processing",
  "progress_pct": 65,
  "current_step": "generating_embeddings"
}
```

Steps: `parsing → chunking → generating_embeddings → storing_vectors → complete`

---

## GET /health

```json
{
  "status": "healthy",
  "checks": { "postgres": "ok", "qdrant": "ok", "redis": "ok", "celery": "ok" }
}
```
