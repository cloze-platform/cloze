"""Report HTML must escape every piece of text it did not write itself.

Report text comes from participants (saved selections and notes), providers
(window titles and descriptions), admins (model names) and models (summaries,
themes, notes). The HTML is put into provider and participant pages with
innerHTML, and rendered to PDF on the server.
"""
import pytest

import llm_chat  # noqa: F401  (import the app package first, as the server does)
from report.renderers.html_renderer import HTMLRenderer
from report.renderers.pdf_renderer import PDFRenderer

PAYLOAD = '<img src=x onerror="alert(1)">'
ESCAPED = "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"


def _report(report_type):
    return {
        "report_type": report_type,
        "generated_at": 0,
        "window_title": PAYLOAD,
        "window_description": PAYLOAD,
        "models_used": {PAYLOAD: {"provider": PAYLOAD}},
        "summary": {"total_conversations": 1, "total_user_messages": 1, "total_model_messages": 1},
        "components": {
            "ai_summary": {
                "summary": f"First sentence. {PAYLOAD}",
                "themes": [PAYLOAD],
                "progress_notes": PAYLOAD,
                "generated_with": PAYLOAD,
            },
            "saved_messages": {
                "total_count": 1,
                "selections": [{"text": PAYLOAD, "note": PAYLOAD, "created_at_formatted": PAYLOAD}],
            },
        },
    }


@pytest.mark.parametrize("renderer", [HTMLRenderer, PDFRenderer])
@pytest.mark.parametrize("report_type", ["summary", "detailed"])
@pytest.mark.parametrize("standalone", [False, True])
def test_report_text_is_escaped(app, renderer, report_type, standalone):
    html = renderer().render_full_report(_report(report_type), standalone=standalone)
    assert "<img" not in html
    assert ESCAPED in html
