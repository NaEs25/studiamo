"""Fingerprints used to reject a PDF or pasted notes the user has already imported."""
from app import storage


def test_notes_hash_ignores_whitespace_but_not_words_or_case():
    base = storage.content_hash_text("Cells divide.\nMitosis has phases.")
    assert base == storage.content_hash_text("  Cells   divide.\r\n\r\nMitosis\thas phases.  ")
    assert base != storage.content_hash_text("Cells divide. Meiosis has phases.")
    assert base != storage.content_hash_text("cells divide. mitosis has phases.")


def test_file_hash_is_exact_bytes():
    assert storage.content_hash_bytes(b"abc") == storage.content_hash_bytes(b"abc")
    assert storage.content_hash_bytes(b"abc") != storage.content_hash_bytes(b"abc ")


def test_empty_notes_hash_is_stable():
    assert storage.content_hash_text("") == storage.content_hash_text("   \n ")
