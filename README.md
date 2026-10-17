# CV RAG Assistant

A local, CV-grounded question-answering API built with FastAPI, Ollama, and ChromaDB. Your documents are indexed on your machine; the app does not require a hosted LLM API key.

## Architecture

1. Put your CV or related documents in the local `documents/` folder.
2. The API checks that folder when the app starts and before each status check or question.
3. If a supported file is added, edited, replaced, or removed, the app refreshes the vector index automatically.
4. Text is extracted and split into overlapping chunks.
5. Ollama's `nomic-embed-text` creates embeddings; ChromaDB stores vectors and source metadata.
6. The app embeds each question, retrieves relevant chunks, and sends only those chunks to the local `qwen2.5:3b` model.
7. The answer includes source filename/page/chunk metadata.

Supported formats: PDF with selectable text, Word DOCX, TXT, and Markdown. Scanned PDFs need OCR first. Folder-based indexing is the recommended workflow. You do not need to retrain the LLM when the CV changes; the document embeddings are refreshed.

The model is instructed not to invent CV details and to say when the indexed documents do not support an answer. Retrieval quality is not perfect, so validate important answers against the source documents. This is a prototype, not a security-reviewed multi-user service.

## Requirements

- Docker Desktop with Docker Compose
- Enough free disk space for the model downloads
- For macOS with 8 GB RAM, close memory-heavy apps while models are running. Performance depends on the machine.

## Start

Clone the repository and enter it:

```bash
git clone https://github.com/adm-l/cv-rag-assistant.git
cd cv-rag-assistant
```

Put your CV into the `documents/` folder, for example `documents/my-cv.pdf` or `documents/my-cv.docx`. The folder is mounted read-only into the API container; edit files on your Mac, not inside Docker.

Start the services:

```bash
docker compose up --build -d
```

Download the models into the Ollama container:

```bash
docker compose exec ollama ollama pull qwen2.5:3b
docker compose exec ollama ollama pull nomic-embed-text
```

Check readiness and index status:

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
curl http://localhost:8000/api/v1/cv/status
```

Open interactive API docs at <http://localhost:8000/docs>.

## Dynamic folder behavior

- The app scans `CV_FOLDER` (default `/documents`) at startup and before `GET /api/v1/cv/status` and `POST /api/v1/ask`.
- It fingerprints file contents, not only timestamps, so saving an edited file triggers a refresh.
- Added, changed, and removed supported files trigger a folder reindex on the next status check or question. No API/server restart is needed.
- Multiple supported documents can live in the folder. The folder contents become the source of truth when they change.
- Ignore unsupported extensions; only PDF, DOCX, TXT, and Markdown are indexed.
- The folder is mounted read-only in Docker so the app can read your files but cannot modify them.

Example workflow: edit `documents/my-cv.docx`, save it, then ask a question again. The next request detects the change and refreshes the index before answering.

## Upload endpoint (optional)

You can also upload one document using the API docs (`POST /api/v1/cv`) or:

```bash
curl -X POST http://localhost:8000/api/v1/cv \
  -F "file=@/absolute/path/to/your-cv.pdf"
```

The upload endpoint is useful for quick testing. For reliable automatic updates, use the `documents/` folder as the source of truth.

## Ask questions

```bash
curl -X POST http://localhost:8000/api/v1/ask \
  -H 'Content-Type: application/json' \
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
| `CV_FOLDER` | `/documents` | Folder scanned for source documents inside the container |
| `RETRIEVAL_TOP_K` | `5` | Number of chunks retrieved |
| `CHUNK_SIZE` | `900` | Approximate characters per chunk |
| `CHUNK_OVERLAP` | `150` | Overlap between adjacent chunks |

Compose uses persistent named volumes for Ollama models and ChromaDB. To stop the services, run `docker compose down`. Do not use `docker compose down -v` unless you intentionally want to delete the downloaded models and indexed documents.

## Tests

Create a local Python environment and run:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

Tests use a fake Ollama client and do not download models. They cover document extraction (including DOCX), chunk validation, ingestion, retrieval, and the empty-index path.

## API

- `GET /healthz` — process health
- `GET /readyz` — checks Ollama reachability
- `GET /api/v1/cv/status` — syncs folder changes and returns index status
- `POST /api/v1/cv` — upload/index one document manually
- `POST /api/v1/ask` — syncs folder changes, then asks a question against the indexed documents

## Privacy and limitations

- Do not upload documents you are not authorized to process.
- Documents stay in your local folder and the local ChromaDB volume. Ollama receives retrieved document chunks and questions over the Docker network.
- No authentication is configured. Keep this service on a trusted local environment; do not expose it publicly without authentication, rate limiting, request-size controls, and a security review.
- PDF extraction reads selectable text only; scanned documents require OCR.
- Similarity retrieval can miss relevant chunks. Source citations and grounded prompting reduce, but do not eliminate, hallucinations.
- Do not put your private CV into Git. The `documents/` folder is intended to be local input; add your documents there after cloning.
