import pytest

from app.rag import CVRAG, RAGError, chunk_text, extract_pages


def test_chunk_text_empty():
    assert chunk_text("   ") == []


def test_chunk_text_overlap_keeps_content():
    text = "A" * 1000
    chunks = chunk_text(text, chunk_size=300, overlap=50)
    assert len(chunks) > 1
    assert all(chunks)
    assert "A" * 300 in chunks[0]


def test_chunk_text_rejects_invalid_overlap():
    with pytest.raises(ValueError):
        chunk_text("hello", chunk_size=10, overlap=10)


def test_extract_text_file():
    pages = extract_pages("cv.txt", b"Go backend engineer")
    assert pages == [{"text": "Go backend engineer", "page": None}]


def test_reject_unsupported_file():
    with pytest.raises(RAGError):
        extract_pages("cv.docx", b"not parsed")


class FakeOllama:
    def embed(self, texts):
        return [[float(len(text)), 1.0, 0.5] for text in texts]

    def generate(self, prompt):
        assert "ONLY the CV context" in prompt
        return "The CV says Go backend engineer. [Source 1]"


def test_ingest_and_ask(tmp_path):
    rag = CVRAG(chroma_path=str(tmp_path / "chroma"), collection_name="test_cv",
                ollama=FakeOllama(), chunk_size=100, chunk_overlap=10, top_k=2)
    result = rag.ingest("cv.txt", b"Go backend engineer with PostgreSQL experience.")
    assert result["chunks_indexed"] >= 1
    answer = rag.ask("What role does the CV describe?")
    assert "Go backend engineer" in answer["answer"]
    assert answer["sources"][0]["filename"] == "cv.txt"


def test_ask_without_cv_fails(tmp_path):
    rag = CVRAG(chroma_path=str(tmp_path / "empty"), collection_name="empty_cv",
                ollama=FakeOllama())
    with pytest.raises(RAGError, match="Upload your CV"):
        rag.ask("What skills do I have?")
