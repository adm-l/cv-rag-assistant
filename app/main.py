from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.config import settings
from app.rag import CVRAG, OllamaClient, RAGError


def build_rag() -> CVRAG:
    ollama = OllamaClient(base_url=settings.ollama_base_url, chat_model=settings.chat_model,
                          embedding_model=settings.embedding_model)
    return CVRAG(chroma_path=settings.chroma_path, collection_name=settings.collection_name,
                 ollama=ollama, chunk_size=settings.chunk_size,
                 chunk_overlap=settings.chunk_overlap, top_k=settings.top_k)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.rag = build_rag()
    yield


app = FastAPI(title="CV RAG Assistant",
    description="Ask questions grounded in your own CV using local Ollama models and ChromaDB.",
    version="1.0.0", lifespan=lifespan)


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
    rag = app.state.rag
    return {"indexed": rag.collection.count() > 0, "chunks": rag.collection.count()}


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
        return app.state.rag.ask(request.question)
    except RAGError as exc:
        status = 409 if "Upload your CV" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Ollama request failed. Check that the required models are installed.") from exc
