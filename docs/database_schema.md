# Database Schema

The submission uses SQLite for metadata and Chroma for retrieved chunks and embeddings.

## SQLite

### `documents`

```sql
CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    file_type TEXT NOT NULL,
    status TEXT NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    deleted_at TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

Query patterns:

- Fetch status by document id
- Mark ingestion as ready or failed
- Mark soft delete state

### `query_logs`

```sql
CREATE TABLE query_logs (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    filters TEXT NOT NULL,
    top_k INTEGER NOT NULL,
    latency_ms INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
```

This keeps minimal evidence of query traffic and latency for the assignment.

## Chroma Collection

Collection: `knowledge_chunks`

Each record stores:

| Field | Location |
|---|---|
| chunk text | Chroma document |
| embedding | Chroma vector |
| `document_id` | metadata |
| `filename` | metadata |
| `file_type` | metadata |
| `chunk_index` | metadata |
| `page` | PDF chunk metadata when available |
| `is_deleted` | metadata |

`document_id` and `file_type` metadata filters narrow vector retrieval. Soft delete keeps vectors but updates `is_deleted`; hard delete removes Chroma records.

## Production Note

For a larger internal platform, SQLite can move to PostgreSQL and Chroma can move to a managed or self-hosted vector database with payload filtering, backup, monitoring, and index tuning. The metadata model stays the same: document rows own many chunk vectors.
