from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import chromadb
import httpx
from pypdf import PdfReader

SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md"}


class RAGError(RuntimeError):
    """Expected error in the RAG pipeline."""


def extract_pages(filename: str, content: bytes) -> list[dict[str, Any]]:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise RAGError("Unsupported file type. Upload a PDF, TXT, or Markdown file.")
    if suffix == ".pdf":
        import io
        try:
            reader = PdfReader(io.BytesIO(content))
            pages = [
                {"text": (page.extract_text() or "").strip(), "page": i + 1}
                for i, page in enumerate(reader.pages)
            ]
        except Exception as exc:
            raise RAGError("Could not read this PDF. If it is scanned, OCR it first.") from exc
        if not any(p["text"] for p in pages):
            raise RAGError("No selectable text found in PDF. OCR scanned documents before uploading.")
        return pages
    text = content.decode("utf-8-sig", errors="replace").strip()
    if not text:
        raise RAGError("The uploaded document is empty.")
    return [{"text": text, "page": None}]


def chunk_text(text: str, chunk_size: int = 900, overlap: int = 150) -> list[str]:
    if chunk_size < 1 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("Require chunk_size > 0 and 0 <= overlap < chunk_size.")
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n", start, end), text.rfind(". ", start, end))
            if boundary > start + chunk_size // 2:
                end = boundary + (1 if text[boundary] == "\n" else 2)
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


class OllamaClient:
    def __init__(self, base_url: str, chat_model: str, embedding_model: str, timeout: float = 120):
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self.timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        with httpx.Client(timeout=self.timeout) as client:
            for text in texts:
                response = client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.embedding_model, "input": text},
                )
                response.raise_for_status()
                data = response.json()
                embeddings = data.get("embeddings") or []
                if not embeddings:
                    raise RAGError("Ollama returned no embedding. Check the embedding model.")
                vectors.append(embeddings[0])
        return vectors

    def generate(self, prompt: str) -> str:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.base_url}/api/generate",
                json={"model": self.chat_model, "prompt": prompt, "stream": False},
            )
            response.raise_for_status()
            result = response.json().get("response", "").strip()
            if not result:
                raise RAGError("The language model returned an empty response.")
            return result


class CVRAG:
    def __init__(self, chroma_path: str, collection_name: str, ollama: OllamaClient,
                 chunk_size: int = 900, chunk_overlap: int = 150, top_k: int = 5):
        self.client = chromadb.PersistentClient(path=chroma_path)
        self.collection = self.client.get_or_create_collection(
            name=collection_name, metadata={"hnsw:space": "cosine"}
        )
        self.ollama = ollama
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.top_k = top_k

    def ingest(self, filename: str, content: bytes) -> dict[str, Any]:
        pages = extract_pages(filename, content)
        records = []
        for page in pages:
            for index, chunk in enumerate(chunk_text(page["text"], self.chunk_size, self.chunk_overlap)):
                records.append({"text": chunk, "page": page["page"], "chunk_index": index})
        if not records:
            raise RAGError("No text chunks could be created from this document.")
        self.collection.delete(where={"document_type": "cv"})
        vectors = self.ollama.embed([r["text"] for r in records])
        digest = hashlib.sha256(content).hexdigest()[:16]
        ids = [f"cv-{digest}-{i}" for i in range(len(records))]
        metadatas = [{"source": Path(filename).name,
                      "page": r["page"] if r["page"] is not None else 0,
                      "chunk_index": r["chunk_index"], "document_type": "cv"} for r in records]
        self.collection.upsert(ids=ids, documents=[r["text"] for r in records],
                               embeddings=vectors, metadatas=metadatas)
        return {"filename": Path(filename).name, "chunks_indexed": len(records), "sha256_prefix": digest}

    def ask(self, question: str) -> dict[str, Any]:
        question = question.strip()
        if not question:
            raise RAGError("Question must not be empty.")
        if self.collection.count() == 0:
            raise RAGError("No CV has been indexed. Upload your CV first.")
        query_vector = self.ollama.embed([question])[0]
        result = self.collection.query(query_embeddings=[query_vector],
            n_results=min(self.top_k, self.collection.count()),
            include=["documents", "metadatas", "distances"])
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        if not docs:
            raise RAGError("No relevant CV content was retrieved.")
        context_parts = []
        sources = []
        for i, (doc, meta, distance) in enumerate(zip(docs, metas, distances), start=1):
            page = meta.get("page", 0)
            source = {"filename": meta.get("source", "CV"), "page": page or None,
                      "chunk_index": meta.get("chunk_index", 0), "distance": round(float(distance), 4)}
            sources.append(source)
            location = f'{source["filename"]}, page {page}' if page else source["filename"]
            context_parts.append(f"[Source {i}: {location}]\n{doc}")
        prompt = f"""You are a CV question-answering assistant.
Answer using ONLY the CV context below. Do not use general knowledge to fill gaps.
Do not invent skills, employers, dates, responsibilities, metrics, or years of experience.
If the context does not support an answer, say: "I couldn't find that information in the indexed CV."
Distinguish explicit facts from cautious calculations. Cite supporting context inline as [Source 1], [Source 2], etc.
Be concise and useful.

CV CONTEXT:
{chr(10).join(context_parts)}

QUESTION:
{question}

ANSWER:"""
        answer = self.ollama.generate(prompt)
        return {"question": question, "answer": answer, "sources": sources}
