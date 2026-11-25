"""The cross-site request check on /api/ (csrf_protect in llm_chat/__init__.py).

State-changing API requests must be JSON, which another site can't send
without a CORS preflight, or multipart with a header only our own pages add.
The check compares the media type alone, lowercased, not substrings of the
raw header.
"""
import pytest

# A route that reads no body, so a request the check lets through gets 404
# (no such chat) and one it stops gets 415.
PATH = "/api/provider/chats/999999"


@pytest.fixture
def researcher(make_user, login_as):
    return login_as(make_user("prov", role="provider"))


@pytest.mark.parametrize("content_type, headers, status", [
    ("application/json", {}, 404),
    ("Application/JSON; charset=utf-8", {}, 404),
    ("multipart/form-data; boundary=X", {"X-Requested-With": "fetch"}, 404),
    # Types another site can send without a preflight:
    ("text/plain", {}, 415),
    ("text/plain; x=application/json", {}, 415),
    ("application/x-www-form-urlencoded", {}, 415),
    ("multipart/form-data; boundary=X", {}, 415),
    ("MULTIPART/FORM-DATA; boundary=X; x=application/json", {}, 415),
    ("Multipart/Form-Data; boundary=X", {"X-Requested-With": "something-else"}, 415),
])
def test_api_requests_need_json_or_same_site_multipart(researcher, content_type, headers, status):
    resp = researcher.delete(PATH, data=b"--X--\r\n", headers={"Content-Type": content_type, **headers})
    assert resp.status_code == status


def test_requests_without_a_type_are_refused(researcher):
    assert researcher.delete(PATH).status_code == 415
