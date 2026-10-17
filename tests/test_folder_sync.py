from app.config import settings
from app.main import folder_documents


def test_folder_fingerprint_changes_when_document_is_edited(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "cv_folder", str(tmp_path))
    document = tmp_path / "cv.txt"
    document.write_text("Go backend engineer", encoding="utf-8")

    first_fingerprint, first_files = folder_documents()
    assert len(first_files) == 1
    assert first_files[0][1] == b"Go backend engineer"

    document.write_text("Senior Go backend engineer", encoding="utf-8")
    second_fingerprint, second_files = folder_documents()

    assert second_fingerprint != first_fingerprint
    assert second_files[0][1] == b"Senior Go backend engineer"


def test_folder_fingerprint_changes_when_document_is_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "cv_folder", str(tmp_path))
    document = tmp_path / "cv.md"
    document.write_text("CV details", encoding="utf-8")

    before, _ = folder_documents()
    document.unlink()
    after, files = folder_documents()

    assert after != before
    assert files == []
