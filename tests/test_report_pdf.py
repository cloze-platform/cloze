"""Report PDFs: they must actually be written, and they must never pull in
local files.

WeasyPrint 62.x silently accepts pydyf versions it cannot write PDFs with
(see the pydyf pin in requirements.txt), so this writes a real PDF instead of
only laying one out. Skipped where WeasyPrint's system libraries (pango) are
not installed.
"""
import time

import pytest

from llm_chat.extensions import db as _db
from llm_chat.models.chat_window import ChatWindow
from report.generator import WEASYPRINT_AVAILABLE, UnifiedReportGenerator, _data_urls_only

pytestmark = pytest.mark.skipif(not WEASYPRINT_AVAILABLE,
                                reason="WeasyPrint or its system libraries are not installed")

REPORT_DATA = {
    "report_type": "summary",
    "generated_at": 0,
    "window_title": "Week 1",
    "summary": {"total_conversations": 1, "total_user_messages": 2, "total_model_messages": 2},
    "components": {
        "ai_summary": {"summary": "The participant talked about sleep. Things improved.",
                       "themes": ["sleep"], "generated_with": "test"},
        "saved_messages": {"total_count": 1, "selections": [
            {"text": "I slept better", "note": "progress", "created_at_formatted": "today"}]},
    },
}


@pytest.fixture
def window(make_user):
    provider = make_user("prov", role="provider")
    patient = make_user("pt", role="user")
    now = time.time()
    w = ChatWindow(patient_id=patient.id, provider_id=provider.id, title="Week 1",
                   start_date=now - 86400, end_date=now)
    _db.session.add(w)
    _db.session.commit()
    return w


@pytest.mark.parametrize("report_type", ["summary", "detailed"])
def test_report_pdf_is_written(window, report_type):
    pdf = UnifiedReportGenerator.export_pdf_from_data(
        window.id, {**REPORT_DATA, "report_type": report_type})
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1000


def test_pdf_fetcher_loads_data_urls_only():
    for url in ("file:///etc/passwd", "http://169.254.169.254/latest/meta-data/"):
        with pytest.raises(ValueError):
            _data_urls_only(url)
    fetched = _data_urls_only("data:text/plain;base64,aGk=")
    assert fetched.get("string") == b"hi" or fetched.get("file_obj") is not None


def test_report_pdf_cannot_embed_local_files(tmp_path):
    import weasyprint

    secret = tmp_path / "secret.txt"
    secret.write_text("not for participants")
    html = f'<p>report</p><link rel="attachment" href="file://{secret}">'

    # WeasyPrint's default fetcher would attach the file to the PDF...
    assert b"/EmbeddedFile" in weasyprint.HTML(string=html).write_pdf()
    # ...the report fetcher refuses it.
    pdf = weasyprint.HTML(string=html, url_fetcher=_data_urls_only).write_pdf()
    assert b"/EmbeddedFile" not in pdf
