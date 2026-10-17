from contextlib import asynccontextmanager
import hashlib
from pathlib import Path

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.config import settings
from app.rag import CVRAG, OllamaClient, RAGError, SUPPORTED_SUFFIXES


def build_rag() -> CVRAG:
    ollama = OllamaClient(base_url=settings.ollama_base_url, chat_model=settings.chat_model,
                          embedding_model=settings.embedding_model)
    return CVRAG(chroma_path=settings.chroma_path, collection_name=settings.collection_name,
                 ollama=ollama, chunk_size=settings.chunk_size,
                 chunk_overlap=settings.chunk_overlap, top_k=settings.top_k)


def folder_documents() -> tuple[str, list[tuple[Path, bytes]]]:
    """Return a content fingerprint and supported files in the configured folder."""
    folder = Path(settings.cv_folder)
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    fingerprint = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        # Do not follow a document symlink outside the configured source folder.
        try:
            path.resolve().relative_to(folder.resolve())
        except ValueError:
            continue
        content = path.read_bytes()
        relative_name = path.relative_to(folder).as_posix()
        digest = hashlib.sha256(content).hexdigest()
        fingerprint.update(relative_name.encode("utf-8"))
        fingerprint.update(digest.encode("ascii"))
        files.append((path, content))
    return fingerprint.hexdigest(), files


def sync_document_folder() -> None:
    """Refresh the index when files are added, edited, replaced, or removed."""
    fingerprint, files = folder_documents()
    if fingerprint == app.state.folder_fingerprint:
        return

    rag = app.state.rag
    # Build embeddings before replacing the old index where possible.
    prepared = []
    for path, content in files:
        prepared.append((path, content))

    # The folder is the source of truth whenever its contents change.
    rag.collection.delete(where={"document_type": "cv"})
    indexed = []
    try:
        for path, content in prepared:
            indexed.append(rag.ingest(path.name, content, replace_existing=False))
    except Exception:
        # Do not mark this folder version as synced; the next request retries.
        raise
    app.state.folder_fingerprint = fingerprint
    app.state.folder_sync = {
        "folder": settings.cv_folder,
        "documents": len(indexed),
        "files": [item["filename"] for item in indexed],
        "chunks_indexed": sum(item["chunks_indexed"] for item in indexed),
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.rag = build_rag()
    app.state.folder_fingerprint = None
    app.state.folder_sync = {"folder": settings.cv_folder, "documents": 0, "files": [], "chunks_indexed": 0}
    try:
        sync_document_folder()
    except Exception:
        # Keep the API available; a later request will retry indexing.
        pass
    yield


app = FastAPI(title="CV RAG Assistant",
    description="Ask questions grounded in local documents using Ollama and ChromaDB.",
    version="1.1.0", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    try:
        with httpx.Client(timeout=2) as client:
            response = client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
            response.raise_for_status()
        return {"status": "ready", "ollama": "reachable"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Ollama is not reachable yet.") from exc


@app.get("/api/v1/cv/status")
def cv_status():
    try:
        sync_document_folder()
    except (RAGError, httpx.HTTPError, OSError) as exc:
        raise HTTPException(status_code=503, detail=f"Could not sync document folder: {exc}") from exc
    rag = app.state.rag
    return {"indexed": rag.collection.count() > 0, "chunks": rag.collection.count(),
            "folder_sync": app.state.folder_sync}


@app.post("/api/v1/cv", status_code=201)
async def upload_cv(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="A filename is required.")
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="File exceeds the 10 MB upload limit.")
    try:
        result = app.state.rag.ingest(file.filename, content)
        return {"message": "CV indexed successfully.", **result}
    except RAGError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Could not reach Ollama or create embeddings. Check model setup.") from exc


@app.post("/api/v1/ask")
def ask_cv(request: AskRequest):
    try:
        sync_document_folder()
        return app.state.rag.ask(request.question)
    except RAGError as exc:
        status = 409 if "No CV has been indexed" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except (httpx.HTTPError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Could not sync documents or reach Ollama. Check folder permissions and model setup.") from exc
