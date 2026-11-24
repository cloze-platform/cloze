"""Report PDFs: they must never pull in local files.

Skipped where WeasyPrint's system libraries (pango) are not installed.
"""
import pytest

from report.generator import WEASYPRINT_AVAILABLE, _data_urls_only

pytestmark = pytest.mark.skipif(not WEASYPRINT_AVAILABLE,
                                reason="WeasyPrint or its system libraries are not installed")


def test_pdf_fetcher_loads_data_urls_only():
    for url in ("file:///etc/passwd", "http://169.254.169.254/latest/meta-data/"):
        with pytest.raises(ValueError):
            _data_urls_only(url)
    fetched = _data_urls_only("data:text/plain;base64,aGk=")
    assert fetched.get("string") == b"hi" or fetched.get("file_obj") is not None
