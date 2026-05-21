# Semantic Search Design

## Ingestion

`POST /documents` stores the file, writes a SQLite document row, and starts ingestion in a FastAPI background task.

PDF pages use PyMuPDF text extraction first. If a page has little or no text, the service uses PyMuPDF OCR backed by Tesseract and keeps the page number in chunk metadata. This is required for `Knowledge_Base_Sample (2).pdf`.

Python source uses LangChain's Python-aware recursive splitter. Text and Markdown use the general recursive splitter.

Current chunk settings:

- chunk size: 1200 characters
- overlap: 180 characters

## Embedding Lifecycle

The service embeds chunks with OpenAI `text-embedding-3-small` and stores them in a persistent Chroma collection.

Each chunk has metadata for:

- document id
- filename
- file type
- chunk index
- PDF page when available
- deletion state

The query endpoint embeds the query with the same embedding model.

## Retrieval

`POST /query` performs Chroma similarity search and returns the top-K chunk records. The API exposes optional `file_type` and `document_id` metadata filters.

The response includes:

- rank
- similarity-style score derived from Chroma distance
- raw chunk content
- filename and document id
- chunk metadata

This keeps validation focused on retrieval instead of answer generation.

## Deletion

Soft delete updates SQLite and marks Chroma chunk metadata as deleted so those chunks are excluded from retrieval.

Hard delete removes Chroma records before removing the SQLite row. If vector deletion fails, metadata remains for recovery.

## Failure Handling

- Empty or unsupported uploads fail at the API boundary.
- Empty extracted content marks the document as failed.
- OCR, embedding, and Chroma errors are stored in the document error field.
- Query embedding or retrieval failures return an API error instead of fabricated results.
