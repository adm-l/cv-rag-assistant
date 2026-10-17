# CV RAG Assistant

A local, CV-grounded question-answering API built with FastAPI, Ollama, and ChromaDB. Your CV is indexed on your machine; the app does not require a hosted LLM API key.

## Architecture

1. Upload a selectable-text PDF, TXT, or Markdown CV.
2. Extract text and split it into overlapping chunks.
3. Generate embeddings with Ollama's `nomic-embed-text`.
4. Store vectors and source metadata in persistent ChromaDB.
5. Embed a question, retrieve the closest chunks, and send only those chunks as context to the local `qwen2.5:3b` model.
6. Return the answer plus source filename/page/chunk metadata.

The model is instructed not to invent CV details and to say when the indexed CV does not support an answer. Retrieval quality is not perfect, so validate important answers against the source CV. This is a prototype, not a security-reviewed multi-user service.

## Requirements

- Docker Desktop with Docker Compose
- Enough free disk space for the model downloads
- For macOS with 8 GB RAM, close memory-heavy apps while models are running. Performance depends on the machine.

## Start

```bash
docker compose up --build -d
```

Download the models into the Ollama container:

```bash
docker compose exec ollama ollama pull qwen2.5:3b
docker compose exec ollama ollama pull nomic-embed-text
```

Check readiness:

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

Open interactive API docs at <http://localhost:8000/docs>.

## Upload your CV

Use the API docs (`POST /api/v1/cv`) or:

```bash
curl -X POST http://localhost:8000/api/v1/cv \\
  -F "file=@/absolute/path/to/your-cv.pdf"
```

Supported file types: PDF, TXT, Markdown. Scanned PDFs need OCR first. Uploading another CV replaces the currently indexed CV. The uploaded CV is stored in the persistent Docker volume and is not committed to Git.

Check status:

```bash
curl http://localhost:8000/api/v1/cv/status
```

## Ask questions

```bash
curl -X POST http://localhost:8000/api/v1/ask \\
  -H 'Content-Type: application/json' \\
  -d '{"question":"Summarize my Go experience and cite the CV evidence."}'
```

Example questions:
- Which backend languages are listed in my CV?
- What microservices or migration projects are described?
- What database, messaging, and caching technologies have I used?
- Which CV evidence is relevant to this job description?

The answer includes `sources`, with filename, PDF page when available, chunk index, and vector distance. These sources identify retrieved context; they are not a guarantee that every generated statement is correct.

## Configuration

Set environment variables in your shell or a local `.env` file (do not commit secrets):

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_CHAT_MODEL` | `qwen2.5:3b` | Local answer-generation model |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model |
| `RETRIEVAL_TOP_K` | `5` | Number of chunks retrieved |
| `CHUNK_SIZE` | `900` | Approximate characters per chunk |
| `CHUNK_OVERLAP` | `150` | Overlap between adjacent chunks |

Compose uses persistent named volumes for Ollama models and ChromaDB. To stop the services, run `docker compose down`. Do not use `docker compose down -v` unless you intentionally want to delete the downloaded models and indexed CV.

## Tests

Create a local Python environment and run:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

Tests use a fake Ollama client and do not download models. They verify document extraction, chunk validation, ingestion, retrieval, and the empty-index path.

## API

- `GET /healthz` — process health
- `GET /readyz` — checks Ollama reachability
- `GET /api/v1/cv/status` — index status
- `POST /api/v1/cv` — upload/index one CV
- `POST /api/v1/ask` — ask a question against the indexed CV

## Privacy and limitations

- Do not upload documents you are not authorized to process.
- The CV is stored in the local ChromaDB volume. Ollama receives CV chunks and questions over the Docker network.
- No authentication is configured. Bind this service to a trusted local environment; do not expose it publicly without authentication, rate limiting, request-size controls, and a security review.
- PDF extraction only reads selectable text; scanned documents require OCR.
- Similarity retrieval can miss relevant chunks. Source citations and grounded prompting reduce, but do not eliminate, hallucinations.
- The app does not include any personal CV data. Upload your own current CV after startup.
