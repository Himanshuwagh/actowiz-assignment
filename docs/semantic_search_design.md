# Semantic Search Design

---

## Chunking

Different file types need different chunking — one size doesn't fit all.

### Knowledge_Base_Sample.pdf

Split by paragraph boundaries, then by size if a paragraph is too long.

- **Chunk size:** 512 tokens
- **Overlap:** 64 tokens (so boundary content isn't lost between chunks)
- **Estimated output:** ~90–100 chunks across 22 pages

### Source_Code_Sample.py

Parsed using Python's `ast` module. Each function and class method becomes its own chunk — not split by character count.

- `DecayProxyRotator.__init__` → chunk
- `DecayProxyRotator.get_proxy` → chunk
- `DecayProxyRotator.report_failure` → chunk
- `UAFreshnessRotator.get_ua` → chunk
- ... and so on

**Why AST?** A query like "how does report_failure work?" should retrieve that exact function, not half of it mixed with unrelated code.

- **Estimated output:** ~10–12 chunks

### Metadata stored per chunk

```json
{
  "document_name": "Source_Code_Sample.py",
  "file_type": "py",
  "chunk_type": "code",
  "class_name": "DecayProxyRotator",
  "function_name": "report_failure",
  "start_line": 57,
  "end_line": 67,
  "is_deleted": false
}
```

For the PDF:
```json
{
  "document_name": "Knowledge_Base_Sample.pdf",
  "file_type": "pdf",
  "chunk_type": "text",
  "page_number": 4,
  "is_deleted": false
}
```

---

## Embedding

**Model:** OpenAI `text-embedding-3-small` (1536 dimensions)

Picked this over `ada-002` (better benchmarks, same price) and `3-large` (5× more expensive, ~3% better — not worth it here).

All ~110 chunks are embedded in a single batched API call. Total cost is effectively zero at this scale.

At query time, the query string is embedded the same way. Redis caches embeddings for repeated queries (TTL: 1 hour) so we don't call OpenAI again for the same question.

---

## Search & Retrieval

**Vector DB:** Qdrant with HNSW index, cosine similarity.

At query time:
1. Embed the query
2. Run ANN search — fetch `top_k × 3` candidates (e.g. 15 for `top_k=5`)
3. Metadata filters applied inside HNSW (no extra DB round-trip)
4. Cross-encoder reranks the 15 candidates, returns top 5

**Cross-encoder model:** `cross-encoder/ms-marco-MiniLM-L-6-v2` — runs locally, no API cost. Adds ~50ms but meaningfully improves precision. Can be disabled with `"rerank": false`.

---

## Failure handling

| What fails | What happens |
|---|---|
| PDF parse error | Job marked `failed`, error stored in `jobs` table |
| OpenAI timeout | Celery retries with exponential backoff (max 5 attempts) |
| Qdrant write fails | Retry; partial chunks cleaned up if unrecoverable |
| Reranker crashes | Falls back to raw Qdrant scores, `rerank_applied: false` in response |
| Query times out | Returns partial results with `"partial": true` |

---

## Sample queries to validate retrieval

**On Source_Code_Sample.py:**
- `"How does the DecayProxyRotator slow down recovery for failing proxies?"` → should retrieve `_calculate_current_score` (uses `penalty_factor`)
- `"What happens when report_failure is called?"` → should retrieve `report_failure` method

**On Knowledge_Base_Sample.pdf:**
- Any natural language question about the document's content should retrieve the relevant paragraph chunks with page attribution
