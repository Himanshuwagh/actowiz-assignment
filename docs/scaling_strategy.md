# Scaling Strategy & Trade-offs

---

## Current state

Two documents ingested: `Knowledge_Base_Sample.pdf` (~95 chunks) and `Source_Code_Sample.py` (~12 chunks). About 107 vectors in Qdrant total. A single FastAPI instance, one Celery worker, and a single Qdrant node handle this comfortably.

The architecture is intentionally lean for now — no point over-engineering for 107 vectors.

---

## How each layer scales

**API (FastAPI)**  
Stateless — any worker can serve any request. Scale horizontally via Kubernetes HPA when CPU > 60% or RPS crosses a threshold. 3 replicas minimum for HA.

**Ingestion workers (Celery)**  
Scale independently from the API. Queue depth triggers new workers. Separate queues for `ingest` and `hard_delete` so a large upload doesn't block a delete operation.

**Vector DB (Qdrant)**  
Currently single node, in-memory. When chunks grow past ~50K, switch to `memmap` storage (vectors on disk, index in RAM). Past 1M vectors, enable distributed mode and shard the collection.

**Postgres**  
Single instance is fine for metadata at this scale. Add a read replica when analytics queries start competing with write traffic. `query_logs` is designed for monthly range partitioning — activate it when rows hit ~100K.

**Redis**  
Handles caching and the job queue. Fine as-is for this scale. If job volume ever crosses ~10K/day, migrate the queue to Kafka (Celery task code doesn't change).

---

## Key trade-offs

| Decision | Why |
|---|---|
| Async ingestion (not sync) | Even a short PDF can take 10–20s to embed; blocking the API would cause timeouts |
| Soft delete by default | Accidental deletes are recoverable; hard delete is opt-in with `?hard=true` |
| OpenAI for embeddings (not self-hosted) | At 100 developers and 2 documents the cost is basically zero; abstracted behind `EmbeddingService` so swapping to a local model later is a one-line change |
| Qdrant over Pinecone | Self-hostable, no vendor lock-in, payload filtering runs inside HNSW (no post-filter overhead) |
| Cross-encoder reranking optional | Adds ~50ms; good default but can be disabled for latency-sensitive integrations |
| Redis for both cache and queue | Simple to operate at this scale; Kafka is overkill for 100 developers |

---

## If the corpus grows significantly

Three things to do when document count starts scaling up:

1. **Switch Qdrant to memmap storage** once the collection exceeds ~50K vectors — vectors move to disk, index stays in RAM, memory pressure drops significantly with minimal latency impact.

2. **Partition `query_logs` by month** — the schema is already range-partitioned on `created_at`. Turn it on before logs exceed ~100K rows so analytics queries don't start scanning the whole table.

3. **Batch embed across documents in parallel** — currently ingestion processes one document at a time. With high upload volume, Celery workers should embed multiple documents concurrently and pre-warm the embedding cache for common query patterns.
