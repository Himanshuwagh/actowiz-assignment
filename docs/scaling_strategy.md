# Scaling Strategy And Trade-offs

## Submission Choice

This repository keeps the runtime small:

- one FastAPI process
- FastAPI background ingestion
- SQLite metadata
- local persistent Chroma
- OpenAI embeddings

That is enough to ingest the two task files through the API and demonstrate semantic retrieval quickly.

## Trade-offs

| Choice | Benefit | Limit |
|---|---|---|
| FastAPI background task | No worker stack to run for the assignment | Work stops if the API process dies |
| SQLite | Zero database setup | Limited concurrent writes and operational tooling |
| Local Chroma | Persistent vector search without another server | Not a multi-node production store |
| OpenAI embeddings | Good retrieval quality with little code | Requires API key and network access |
| OCR fallback | Makes the provided image-based PDF searchable | OCR is slower and can introduce text noise |

## Production Path

At higher upload volume:

1. Move ingestion to a worker queue so OCR, chunking, and embedding retries survive API restarts.
2. Move document metadata and query logs to PostgreSQL.
3. Use object storage for original uploads.
4. Use a production vector store with backup, replication, metadata indexes, and monitoring.
5. Add auth, rate limits, deduplication, embedding retry policy, metrics, and tracing.

Soft delete should stay the default for accidental deletion recovery. Hard delete should be a controlled cleanup path that deletes vectors and metadata with retries.
