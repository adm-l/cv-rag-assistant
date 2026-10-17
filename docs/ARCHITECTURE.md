# CV RAG Assistant — Architecture and Request Lifecycle

## Purpose

This application answers questions grounded in local CV and supporting documents. It combines retrieval with a locally running language model. It does not train or fine-tune the model on your CV.

## High-level architecture

~~~mermaid
flowchart TD
    U[User / curl / Swagger] --> API[FastAPI :8000]
    DOCS[Host documents folder] -->|read-only mount| SYNC[Folder synchronizer]
    subgraph Compose
      API --> SYNC
      SYNC --> EXT[PDF / DOCX / TXT / Markdown extraction]
      EXT --> CHUNK[Chunking with overlap]
      CHUNK --> EMB[Ollama embedding model]
      EMB --> DB[(ChromaDB vector collection)]
      API --> Q[Embed question]
      Q --> RET[Similarity retrieval]
      DB --> RET
      RET --> PROMPT[Question + retrieved evidence]
      PROMPT --> CHAT[Ollama chat model]
      CHAT --> ANSWER[Answer + source metadata]
    end
    ANSWER --> U
~~~

There are two main paths: **ingestion**, which makes documents searchable, and **question answering**, which retrieves evidence and generates an answer.

## Components

| Component | Responsibility |
|---|---|
| FastAPI (app/main.py) | HTTP endpoints, request validation and orchestration |
| RAG implementation (app/rag.py) | Extraction, chunking, folder fingerprints, embedding, indexing, retrieval and prompt construction |
| Configuration (app/config.py) | Environment-driven settings |
| Ollama | Runs local embedding and chat models and exposes an HTTP API |
| nomic-embed-text | Converts document chunks and questions into vectors |
| qwen2.5:3b (default) | Generates answers using the retrieved evidence |
| ChromaDB | Persists vectors and source metadata and performs similarity search |
| documents/ | Source-of-truth folder for CV and related files |

## Ingestion lifecycle

1. Place a CV or related document in the host documents/ folder. Docker mounts it read-only inside the API container at /documents.
2. At startup, and before the CV status and ask endpoints, the app scans supported files: PDF, DOCX, TXT and Markdown.
3. File contents are fingerprinted so additions, edits and removals can be detected.
4. Supported documents are parsed into text. PDFs must contain selectable text; scanned PDFs require OCR first.
5. Text is split into chunks of approximately CHUNK_SIZE characters with CHUNK_OVERLAP characters shared between neighboring chunks. Overlap helps preserve context at boundaries.
6. Ollama's configured embedding model converts each chunk to a vector.
7. ChromaDB stores vectors and metadata such as source filename, page where available and chunk index.
8. The next status request or question synchronizes the index when source files have changed.

**Changing a CV does not require model retraining.** The document index and embeddings are refreshed on the next status check or ask request. This is request-triggered synchronization, not a continuous filesystem watcher.

## Question-answering lifecycle

1. The client sends JSON to POST /api/v1/ask, for example: {"question":"Summarize my Go experience"}.
2. The API synchronizes the document folder to include recent edits.
3. The question is embedded using the same embedding model as the indexed chunks.
4. ChromaDB retrieves the nearest chunks. RETRIEVAL_TOP_K defaults to 5.
5. The application constructs a prompt containing the question and retrieved evidence, asking the chat model not to invent unsupported CV facts.
6. Ollama's chat model generates a response.
7. The API returns the answer and source metadata. Sources show retrieved context but do not guarantee that every generated statement is correct.

RAG means Retrieval-Augmented Generation: retrieval selects external evidence at request time, and generation uses that evidence to compose an answer. The vector database is not the LLM, and embeddings are not the final answer.

## Model selection

- OLLAMA_CHAT_MODEL chooses the answer-generation model; default qwen2.5:3b.
- OLLAMA_EMBED_MODEL chooses the embedding model; default nomic-embed-text.

These models perform different jobs. To change the chat model, pull the exact model tag into Ollama, change OLLAMA_CHAT_MODEL in Compose or the Compose environment, then recreate the API container. Different models vary in latency, memory use and answer quality.

Keep the embedding model consistent with the one used to create the existing index. Changing embedding models generally requires rebuilding the vector index because vectors from different embedding spaces cannot safely be compared.

## Runtime and persistence

- FastAPI is published on host port 8000.
- Ollama is published on host port 11434. Containers reach it at http://ollama:11434 on the Compose network.
- ollama_data persists downloaded model files.
- chroma_data persists the vector index.
- documents/ is mounted read-only, so the application can read but cannot modify source files.

docker compose down stops containers but keeps named volumes. docker compose down -v also deletes the named volumes, including downloaded models and the ChromaDB index.

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | /healthz | Basic process health |
| GET | /readyz | Checks Ollama reachability |
| GET | /api/v1/cv/status | Synchronizes folder and reports index status |
| POST | /api/v1/cv | Uploads and indexes one document |
| POST | /api/v1/ask | Synchronizes, retrieves evidence and generates an answer |
| GET | /docs | Interactive Swagger UI |

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| OLLAMA_BASE_URL | http://ollama:11434 in Compose | Ollama API address from API container |
| OLLAMA_CHAT_MODEL | qwen2.5:3b | Chat/generation model |
| OLLAMA_EMBED_MODEL | nomic-embed-text | Embedding model |
| CV_FOLDER | /documents | Folder scanned inside container |
| CHROMA_PATH | /data/chroma | Vector database path |
| CHROMA_COLLECTION | cv_chunks | ChromaDB collection |
| CHUNK_SIZE | 900 | Approximate characters per chunk |
| CHUNK_OVERLAP | 150 | Shared characters between adjacent chunks |
| RETRIEVAL_TOP_K | 5 | Maximum retrieved chunks |
| MAX_UPLOAD_BYTES | 10485760 | Upload limit (10 MiB) |

## Privacy, reliability and limitations

- Similarity retrieval can miss useful sections; verify important answers against the CV.
- Scanned PDFs need OCR, which is not performed automatically.
- Local inference consumes memory, CPU/GPU and disk space. On an 8 GB Mac, close memory-heavy applications and use a small model.
- This is a local prototype without authentication. Do not expose it publicly without authentication, rate limiting, request-size controls, monitoring and a security review.
- Treat document contents as untrusted input. Retrieved text should be evidence, not instructions that override application policy.
