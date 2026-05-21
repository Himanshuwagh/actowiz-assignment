from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pymupdf
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, UploadFile, status
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import Language, RecursiveCharacterTextSplitter
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("RAG_DATA_DIR", BASE_DIR / ".rag_data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "metadata.db"
CHROMA_DIR = DATA_DIR / "chroma"
COLLECTION_NAME = "knowledge_chunks"
SUPPORTED_FILE_TYPES = {".pdf": "pdf", ".py": "py", ".txt": "txt", ".md": "md"}

app = FastAPI(title="Internal AI Knowledge Platform", version="1.0.0")


class QueryFilters(BaseModel):
    file_type: str | None = None
    document_id: str | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    filters: QueryFilters = Field(default_factory=QueryFilters)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    with connect_db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
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
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS query_logs (
                id TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                filters TEXT NOT NULL,
                top_k INTEGER NOT NULL,
                latency_ms INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model="text-embedding-3-small")


def get_vector_store() -> Chroma:
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=get_embeddings(),
        persist_directory=str(CHROMA_DIR),
    )


def file_type_for(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_FILE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Supported files are PDF, Python, text, and Markdown.",
        )
    return SUPPORTED_FILE_TYPES[suffix]


def get_document_row(document_id: str) -> sqlite3.Row:
    with connect_db() as connection:
        row = connection.execute(
            "SELECT * FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return row


def update_document(document_id: str, **fields: Any) -> None:
    fields["updated_at"] = utc_now()
    assignments = ", ".join(f"{name} = ?" for name in fields)
    values = list(fields.values()) + [document_id]
    with connect_db() as connection:
        connection.execute(f"UPDATE documents SET {assignments} WHERE id = ?", values)


def store_upload(document_id: str, filename: str, content: bytes) -> Path:
    suffix = Path(filename).suffix.lower()
    stored_path = UPLOAD_DIR / f"{document_id}{suffix}"
    stored_path.write_bytes(content)
    return stored_path


def extract_pdf_pages(file_path: Path) -> list[Document]:
    pages: list[Document] = []
    with pymupdf.open(file_path) as pdf:
        for page_number, page in enumerate(pdf, start=1):
            text = page.get_text("text").strip()
            if len(text) < 40:
                text_page = page.get_textpage_ocr(language="eng", full=True)
                text = page.get_text("text", textpage=text_page).strip()
            if text:
                pages.append(Document(page_content=text, metadata={"page": page_number}))
    return pages


def extract_source_document(file_path: Path, file_type: str) -> list[Document]:
    content = file_path.read_text(encoding="utf-8", errors="ignore").strip()
    if not content:
        return []
    return [Document(page_content=content, metadata={"file_type": file_type})]


def split_pdf_pages(pages: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=180)
    return splitter.split_documents(pages)


def split_source_documents(documents: list[Document], file_type: str) -> list[Document]:
    if file_type == "py":
        splitter = RecursiveCharacterTextSplitter.from_language(
            Language.PYTHON,
            chunk_size=1200,
            chunk_overlap=180,
        )
    else:
        splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=180)
    return splitter.split_documents(documents)


def chunks_for(file_path: Path, file_type: str) -> list[Document]:
    if file_type == "pdf":
        return split_pdf_pages(extract_pdf_pages(file_path))
    return split_source_documents(extract_source_document(file_path, file_type), file_type)


def ingest_document(document_id: str) -> None:
    try:
        row = get_document_row(document_id)
        chunks = chunks_for(Path(row["stored_path"]), row["file_type"])
        if not chunks:
            raise ValueError("No extractable content found in the uploaded file.")

        chunk_ids = []
        for chunk_index, chunk in enumerate(chunks):
            chunk.metadata.update(
                {
                    "document_id": document_id,
                    "filename": row["filename"],
                    "file_type": row["file_type"],
                    "chunk_index": chunk_index,
                    "is_deleted": False,
                }
            )
            chunk_ids.append(f"{document_id}:{chunk_index}")

        get_vector_store().add_documents(chunks, ids=chunk_ids)
        update_document(document_id, status="ready", chunk_count=len(chunks), error=None)
    except Exception as exc:
        update_document(document_id, status="failed", error=str(exc))


def build_filter(filters: QueryFilters) -> dict[str, Any]:
    conditions: list[dict[str, Any]] = [{"is_deleted": False}]
    if filters.file_type:
        conditions.append({"file_type": filters.file_type.lower()})
    if filters.document_id:
        conditions.append({"document_id": filters.document_id})
    return conditions[0] if len(conditions) == 1 else {"$and": conditions}


def distance_to_score(distance: float) -> float:
    return round(max(0.0, 1.0 - distance), 4)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/documents", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    filename = file.filename or "upload"
    file_type = file_type_for(filename)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    document_id = str(uuid4())
    created_at = utc_now()
    stored_path = store_upload(document_id, filename, content)
    with connect_db() as connection:
        connection.execute(
            """
            INSERT INTO documents (
                id, filename, stored_path, file_type, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (document_id, filename, str(stored_path), file_type, "processing", created_at, created_at),
        )

    background_tasks.add_task(ingest_document, document_id)
    return {"document_id": document_id, "filename": filename, "file_type": file_type, "status": "processing"}


@app.get("/documents/{document_id}")
def document_status(document_id: str) -> dict[str, Any]:
    row = get_document_row(document_id)
    return {
        "document_id": row["id"],
        "filename": row["filename"],
        "file_type": row["file_type"],
        "status": row["status"],
        "chunk_count": row["chunk_count"],
        "deleted": bool(row["is_deleted"]),
        "error": row["error"],
        "created_at": row["created_at"],
    }


@app.post("/query")
def query_documents(request: SearchRequest) -> dict[str, Any]:
    started_at = time.perf_counter()
    try:
        results = get_vector_store().similarity_search_with_score(
            request.query,
            k=request.top_k,
            filter=build_filter(request.filters),
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    latency_ms = int((time.perf_counter() - started_at) * 1000)
    with connect_db() as connection:
        connection.execute(
            """
            INSERT INTO query_logs (id, query, filters, top_k, latency_ms, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                request.query,
                json.dumps(request.filters.model_dump(exclude_none=True)),
                request.top_k,
                latency_ms,
                utc_now(),
            ),
        )

    return {
        "query": request.query,
        "top_k": request.top_k,
        "latency_ms": latency_ms,
        "results": [
            {
                "rank": rank,
                "score": distance_to_score(distance),
                "content": chunk.page_content,
                "document_id": chunk.metadata["document_id"],
                "filename": chunk.metadata["filename"],
                "file_type": chunk.metadata["file_type"],
                "metadata": chunk.metadata,
            }
            for rank, (chunk, distance) in enumerate(results, start=1)
        ],
    }


@app.delete("/documents/{document_id}")
def delete_document(document_id: str, hard: bool = Query(default=False)) -> dict[str, Any]:
    row = get_document_row(document_id)
    if hard:
        try:
            get_vector_store().delete(where={"document_id": document_id})
            with connect_db() as connection:
                connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            return {"document_id": document_id, "status": "hard_deleted"}
        except Exception as exc:
            update_document(document_id, status="delete_failed", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Hard delete failed. Metadata was kept for recovery.",
            ) from exc

    deleted_at = utc_now()
    stored_chunks = get_vector_store().get(
        where={"document_id": document_id},
        include=["documents", "metadatas"],
    )
    if stored_chunks["ids"]:
        get_vector_store().update_documents(
            ids=stored_chunks["ids"],
            documents=[
                Document(
                    page_content=content,
                    metadata={**metadata, "is_deleted": True},
                )
                for content, metadata in zip(stored_chunks["documents"], stored_chunks["metadatas"])
            ],
        )
    update_document(document_id, is_deleted=1, deleted_at=deleted_at, status="deleted")
    return {"document_id": document_id, "status": "soft_deleted", "deleted_at": deleted_at}
