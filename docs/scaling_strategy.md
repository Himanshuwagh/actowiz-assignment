# Scaling Strategy And Trade-offs

## Starting Point

This submission is built to prove the full RAG flow with low setup cost:

- API upload of the provided PDF and Python file
- extraction, chunking, embedding, and persistent vector storage
- semantic retrieval with metadata filters
- soft and hard document deletion

The implementation is deliberately single-service. That is a delivery choice for an assignment, not the target operating model for an internal knowledge platform used by many teams.

## Where The System Will Feel Pressure First

The first scaling problem is ingestion, not query routing.

PDF OCR and embedding calls are slower and less predictable than status reads or vector queries. The provided PDF already demonstrates that extraction cannot assume every document has a usable text layer. If several users upload scanned PDFs at once, a FastAPI background task model starts competing with request handling and loses work if the process restarts.

The second pressure point is persistence. Local SQLite and local Chroma are practical for a reviewer running one service instance. They stop being a clean choice once multiple API replicas need shared document state, shared vector data, backups, and operational visibility.

## Evolution Plan

### 1. Separate Request Handling From Ingestion

Move upload processing behind a durable job queue.

| Keep in API | Move to workers |
|---|---|
| validate file and create document record | OCR and text extraction |
| store original upload reference | chunking |
| return document id and status | batch embedding |
| expose job/document status | vector-store writes |

Workers make failures explicit and retryable. They also allow OCR-heavy uploads to scale independently from the query API.

### 2. Make Storage Shared And Durable

The next storage step would be:

- object storage for raw files
- PostgreSQL for documents, jobs, and query logs
- a production vector store for embeddings and chunk metadata

The service boundary should remain the same even if the vector backend changes. The application should ask for "store chunks", "search chunks", and "delete document vectors"; it should not leak store-specific behavior through the public API.

### 3. Scale Retrieval Separately

Query traffic has a different profile from ingestion:

- it is latency-sensitive
- it depends on embedding the user query
- it reads many vectors but writes only a small log record

Once query volume grows, the API can scale horizontally because it is mostly stateless after storage is externalized. The next optimizations should be driven by measurements, usually starting with embedding latency, vector-search latency, and the quality of top-K retrieval under metadata filters.

## Reliability Decisions

### Async ingestion

Uploads should not block on OCR and embedding work. The current background-task implementation demonstrates that contract. A production worker model keeps the same API behavior while making retries and progress tracking reliable.

### Deletion behavior

Soft delete should be the default because knowledge-base deletes are operationally risky and source content may need recovery. Hard delete is still required for cleanup or retention rules, but it should be implemented as a retried workflow that removes vector records and metadata in a controlled order.

### Failure visibility

Ingestion failures should attach to document state rather than disappear into worker logs. The current `failed` status and `error` field are small but important: they give the client a direct reason a file is not queryable.

## Trade-offs In This Submission

| Decision | Why it fits here | What changes later |
|---|---|---|
| FastAPI background tasks | Minimal runtime while preserving async upload semantics | Durable queue and workers |
| SQLite metadata | No external database needed for review | PostgreSQL with migrations and operational indexes |
| Local Chroma | Persistent vector search with metadata filters | Production vector store and capacity planning |
| OpenAI embeddings | Good quality with little infrastructure | Add rate-limit handling, cost controls, provider abstraction |
| OCR fallback | Required for the supplied image-based PDF | Add OCR metrics and extraction-quality evaluation |

## Guardrails Before Broad Internal Use

Before treating this as an internal platform rather than an assignment, I would add:

1. authentication and authorization for uploads, queries, and deletes
2. content-size limits, file scanning policy, and upload deduplication
3. retry policy and backoff for embedding and vector-store failures
4. metrics for ingestion duration, chunk counts, query latency, and retrieval failures
5. tracing across upload, worker execution, embedding calls, and vector writes
6. backup and retention policy for raw files, metadata, and vector collections

## Scaling Summary

The current design optimizes for reviewability and a working end-to-end demo. The production path is not to add complexity everywhere at once; it is to externalize the slow and stateful parts first, then scale ingestion and retrieval according to their different workloads.
