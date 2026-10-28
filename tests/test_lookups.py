"""Primary-key lookups (db.session.get / db.get_or_404): known IDs are found,
unknown IDs give a 404 rather than an error."""
import time

from llm_chat.extensions import db as _db
from llm_chat.models.chat_window import ChatWindow
from llm_chat.models.core import ProviderPatient

JSON_HEADERS = {"Content-Type": "application/json"}


def test_known_id_is_found(login_as, make_user):
    admin = make_user("admin1", role="admin")
    target = make_user("pt1", role="user")

    resp = login_as(admin).post(
        f"/api/admin/user/{target.id}/toggle-visibility",
        json={"visible": False}, headers=JSON_HEADERS,
    )

    assert resp.status_code == 200
    assert resp.get_json()["visible"] is False


def test_unknown_ids_return_404(login_as, make_user):
    admin = make_user("admin1", role="admin")
    client = login_as(admin)

    assert client.post("/api/admin/user/99999/toggle-visibility",
                       json={}, headers=JSON_HEADERS).status_code == 404
    assert client.get("/admin/transcript/99999").status_code == 404
    assert client.get("/api/reports/window/99999").status_code == 404


def test_provider_window_lookup(login_as, make_user):
    provider = make_user("prov", role="provider")
    patient = make_user("pt", role="user")
    _db.session.add(ProviderPatient(provider_id=provider.id, patient_id=patient.id))
    now = time.time()
    window = ChatWindow(patient_id=patient.id, provider_id=provider.id, title="W",
                        start_date=now, end_date=now + 3600)
    _db.session.add(window)
    _db.session.commit()

    client = login_as(provider)
    # Found, but no report yet: the route's own "not found" message, not a bare 404 page.
    resp = client.get(f"/api/reports/window/{window.id}")
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "Report not found"}
