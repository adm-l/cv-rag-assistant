# CV RAG Assistant — Installation, Running and Troubleshooting

This guide covers macOS with Docker Desktop. FastAPI serves the API, Ollama runs the local models, and ChromaDB persists the vector index.

## 1. Prerequisites

- Docker Desktop installed and running.
- Git and a terminal.
- Free disk space for container images and model downloads.
- For an 8 GB RAM Mac, begin with the default small chat model and close memory-intensive apps.

Verify the tools:

~~~bash
git --version
docker --version
docker compose version
docker info
~~~

If docker info cannot connect to the daemon, open Docker Desktop and wait until it is running.

## 2. Clone the repository

~~~bash
git clone https://github.com/adm-l/cv-rag-assistant.git
cd cv-rag-assistant
ls
ls app
ls documents
~~~

## 3. Add your CV

Copy your CV into the local documents/ folder. Example:

~~~bash
cp ~/Downloads/my-cv.pdf documents/my-cv.pdf
~~~

Supported formats are PDF with selectable text, DOCX, TXT and Markdown. Scanned PDFs need OCR first. Do not commit a private CV to Git. The folder is mounted read-only into the API container; edit files on your Mac.

## 4. Build and start

~~~bash
docker compose up --build -d
docker compose ps
docker compose logs --tail=100 api
docker compose logs --tail=100 ollama
~~~

The Compose architecture has:
- api: FastAPI published at http://localhost:8000
- ollama: local model runtime published at http://localhost:11434
- ollama_data: persistent model-download volume
- chroma_data: persistent vector-index volume
- documents/: local source files mounted read-only at /documents

The API may start before model downloads are complete. Continue with the next step.

## 5. Download required models

~~~bash
docker compose exec ollama ollama pull qwen2.5:3b
docker compose exec ollama ollama pull nomic-embed-text
docker compose exec ollama ollama list
~~~

The chat model generates the answer. The embedding model converts document chunks and questions into vectors for similarity search. These are separate model roles.

## 6. Check health and indexing

~~~bash
curl -i http://localhost:8000/healthz
curl -i http://localhost:8000/readyz
curl -sS http://localhost:8000/api/v1/cv/status
~~~

Open [Swagger UI](http://localhost:8000/docs) to explore and call the API interactively. The CV status request also triggers a folder scan and index synchronization.

## 7. Ask a question

~~~bash
curl -sS -X POST http://localhost:8000/api/v1/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Summarize my Go experience and cite the CV evidence."}'
~~~

Example questions:
- Which backend languages and frameworks are listed?
- What projects mention Go microservices?
- Which databases, messaging systems and caching tools are listed?
- Which experience in my CV is relevant to a job description?

The response includes source metadata such as filename, page where available, chunk index and vector distance. Verify important claims against the original CV.

## 8. Verify dynamic CV updates

1. Edit a file in the host documents/ folder and save it.
2. Call GET /api/v1/cv/status or send another question.
3. The application fingerprints file contents and refreshes the index when it detects additions, changes or removals.
4. Ask about the changed content.

No server restart or model retraining should be needed for normal folder-based updates. Synchronization happens on the next status or ask request, not through a continuous background file watcher.

## 9. Change the chat model

1. Pull the exact desired Ollama model tag, for example: docker compose exec ollama ollama pull <model-tag>.
2. Set OLLAMA_CHAT_MODEL to that exact tag in compose.yaml or the Compose environment.
3. Recreate the API container so it receives the new environment:

~~~bash
docker compose up -d --force-recreate api
docker compose logs --tail=100 api
~~~

Ask a test question. Model choices trade off quality, speed and memory. Keep the embedding model consistent with the one used to create the current index. Changing embedding models may require rebuilding the ChromaDB index.

## 10. Run tests without model downloads

The tests use a fake Ollama client and should not require live model inference:

~~~bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pytest -q
~~~

Use Python 3.12 to match the Docker image if your local Python version causes dependency issues.

## 11. Useful commands

~~~bash
docker compose ps
docker compose logs -f api
docker compose logs -f ollama
docker compose restart
docker compose up --build -d api
docker compose exec ollama ollama list
docker compose down
df -h
~~~

docker compose down preserves named volumes. Avoid docker compose down -v unless you intentionally want to delete the persistent model files and ChromaDB index.

## 12. Troubleshooting

### Docker daemon unavailable
Open Docker Desktop, wait for startup to complete, then retry docker info.

### API cannot reach Ollama
Check docker compose ps and docker compose logs --tail=200 ollama. Inside Compose, the API should use http://ollama:11434. localhost inside the API container refers to that API container, not the Ollama service.

### Model missing
Run docker compose exec ollama ollama list and pull the exact tag configured in Compose.

### First answer is slow
The first inference may load model weights into memory. On an 8 GB Mac, close memory-heavy apps and avoid running multiple large models simultaneously.

### No relevant CV content found
Call the CV status endpoint. Confirm the file is supported and that a PDF has selectable text. Ask a narrower question and inspect the returned source metadata.

### CV edits do not appear
Edit the host documents/ folder, then call GET /api/v1/cv/status to trigger synchronization. Unsupported extensions are ignored.

### Port already in use
Stop the conflicting service or change the published host port in compose.yaml. If you change a host port, update browser and curl URLs. The internal Compose address for Ollama remains http://ollama:11434.

### Clean index
Avoid deleting all Docker volumes as the first step: that also deletes model downloads. Back up important data and inspect the ChromaDB configuration before removing its index volume.

## 13. Security

This is a local prototype without API authentication. Do not expose port 8000 to untrusted networks or the public internet without authentication, rate limiting, upload validation, request-size controls, monitoring and a security review. Keep private CV files out of Git.
