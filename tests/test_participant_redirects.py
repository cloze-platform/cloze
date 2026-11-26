"""Today's participant links, once participant_ui is v2."""

import pytest

from llm_chat.models import AdminSettings


def _location(client, path):
    resp = client.get(path)
    assert resp.status_code == 302, (path, resp.status_code)
    return resp.headers["Location"]


@pytest.mark.parametrize("path, v1, v2_target", [
    ("/conversation/{id}", "/dashboard?conversation={id}", "/exercise/{id}"),
    ("/dashboard?conversation={id}", None, "/exercise/{id}"),
    ("/my-reports", "/dashboard", "/reports"),
    ("/chat-windows", "/dashboard", "/dashboard"),
])
def test_old_participant_links(study, login_as, db, path, v1, v2_target):
    conv_id = study["thoughts_conv"].id
    path, client = path.format(id=conv_id), login_as(study["patient"])
    if v1:
        assert _location(client, path).endswith(v1.format(id=conv_id))
    else:
        assert client.get(path).status_code == 200            # today's page handles it itself
    db.session.add(AdminSettings(setting_name="participant_ui", setting_value="v2"))
    db.session.commit()
    assert _location(login_as(study["patient"]), path).endswith(v2_target.format(id=conv_id))


def test_another_participants_conversation_stays_closed(study, login_as, v2):
    other = study["other"]
    assert login_as(other).get(f"/conversation/{study['thoughts_conv'].id}").status_code == 403
    client = login_as(other)
    assert client.get(_location(client, f"/dashboard?conversation={study['thoughts_conv'].id}")).status_code == 404


def test_researchers_keep_the_conversation_page(study, login_as, v2):
    resp = login_as(study["provider"]).get(f"/conversation/{study['thoughts_conv'].id}")
    assert resp.status_code == 200 and 'id="composer"' not in resp.get_data(as_text=True)


@pytest.mark.parametrize("value", ["abc", "", "1;2"])
def test_a_bad_conversation_link_just_opens_home(study, login_as, v2, value):
    assert login_as(study["patient"]).get(f"/dashboard?conversation={value}").status_code == 200
