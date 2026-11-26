"""The Reports page: only the participant's own summary reports, today's content."""

import json

import pytest

from llm_chat.models import AdminSettings, ProviderFeatureFlags, Report

PAYLOAD = '<img src=x onerror="alert(1)">'


def _report(db, study, window, report_type="summary", patient=None, summary="A good week."):
    data = {"report_type": report_type, "generated_at": 0, "window_title": window.title,
            "summary": {"total_conversations": 1, "total_user_messages": 2, "total_model_messages": 2},
            "components": {"ai_summary": {"summary": summary, "themes": [], "progress_notes": ""}}}
    r = Report(window_id=window.id, patient_id=(patient or study["patient"]).id, provider_id=study["provider"].id,
               report_type=report_type, report_data=json.dumps(data), generated_at=1_799_000_000 + window.id)
    db.session.add(r)
    db.session.commit()
    return r


def _main(client, path="/reports"):
    resp = client.get(path)
    assert resp.status_code == 200, resp.status_code
    html = resp.get_data(as_text=True)
    return html[html.index("<main"):html.index("</main>")]


def test_lists_own_summaries_and_opens_the_newest(study, login_as, v2, db):
    pilot = _report(db, study, study["pilot"], summary="Pilot summary.")
    intro = _report(db, study, study["intro"], summary="Intro summary.")
    intro.generated_at = pilot.generated_at + 60                              # the newest
    db.session.commit()
    _report(db, study, study["intro"], report_type="detailed", summary="Detailed only.")
    _report(db, study, study["hidden"], summary="Hidden window.")
    main = _main(login_as(study["patient"]))
    nav = main[main.index('aria-label="Your reports"'):main.index("</nav>")]
    assert "Intro" in nav and "Pilot" in nav and "Hidden" not in nav
    assert f'href="/reports/{intro.id}" aria-current="page"' in nav
    assert "Intro summary." in main and "Detailed only." not in main
    assert f'href="/api/reports/download/{intro.id}/pdf"' in main
    assert f'href="/exercise/{study["welcome_conv"].id}"' in main            # back to the conversation
    assert "Pilot summary." in _main(login_as(study["patient"]), f"/reports/{pilot.id}")


def test_report_text_is_escaped(study, login_as, v2, db):
    _report(db, study, study["pilot"], summary=f"Fine. {PAYLOAD}")
    main = _main(login_as(study["patient"]))
    assert "<img src=x" not in main and "&lt;img src=x" in main


@pytest.mark.parametrize("which", ["other", "detailed", "hidden"])
def test_reports_that_are_not_yours_to_open_are_404(study, login_as, v2, db, which):
    window = study["hidden"] if which == "hidden" else study["pilot"]
    report = _report(db, study, window, report_type="detailed" if which == "detailed" else "summary",
                     patient=study["other"] if which == "other" else None)
    assert login_as(study["patient"]).get(f"/reports/{report.id}").status_code == 404


def test_being_prepared(study, login_as, v2):
    main = _main(login_as(study["patient"]))
    assert "Intro" in main and "Being prepared" in main                     # ended, no report yet


def test_nothing_yet(make_user, login_as, v2):
    assert "No reports yet" in _main(login_as(make_user("new")))


def test_404_when_reports_are_off(study, login_as, v2, db):
    db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id, enable_nlp_report=False))
    db.session.commit()
    assert login_as(study["patient"]).get("/reports").status_code == 404


def test_my_reports_goes_to_the_new_page_on_v2(study, login_as, db):
    assert login_as(study["patient"]).get("/my-reports").headers["Location"].endswith("/dashboard")
    db.session.add(AdminSettings(setting_name="participant_ui", setting_value="v2"))
    db.session.commit()
    assert login_as(study["patient"]).get("/my-reports").headers["Location"].endswith("/reports")


def test_a_window_with_a_report_is_not_being_prepared(study, login_as, v2, db):
    _report(db, study, study["intro"])
    main = _main(login_as(study["patient"]))
    assert "Being prepared" not in main
    assert "being prepared" not in login_as(study["patient"]).get("/dashboard").get_data(as_text=True)


# ── The report API: what a participant may read (GHSA-q2w6-964m-7xh5) ──

def _paths(report):
    return [f"/api/reports/{report.id}", f"/api/reports/html/{report.id}", f"/api/reports/download/{report.id}/html"]


def test_participants_read_their_own_summaries(study, login_as, db):
    summary = _report(db, study, study["pilot"])
    client = login_as(study["patient"])
    for path in _paths(summary):
        assert client.get(path).status_code == 200, path
    # today's dashboard: the window's report, then its HTML
    assert client.get(f"/api/reports/window/{study['pilot'].id}").get_json()["id"] == summary.id
    assert client.get(f"/api/reports/download/window/{study['pilot'].id}/summary/html").status_code == 200


def test_detailed_reports_are_for_the_research_team(study, login_as, db):
    _report(db, study, study["pilot"])
    detailed = _report(db, study, study["pilot"], report_type="detailed", summary="For researchers.")
    client = login_as(study["patient"])
    for path in _paths(detailed) + [f"/api/reports/download/window/{study['pilot'].id}/detailed/html"]:
        assert client.get(path).status_code == 404, path
    window_report = client.get(f"/api/reports/window/{study['pilot'].id}?type=detailed").get_json()
    assert window_report["report_type"] == "summary"
    assert login_as(study["provider"]).get(f"/api/reports/html/{detailed.id}").status_code == 200


def test_reports_from_hidden_windows_are_closed(study, login_as, db):
    hidden = _report(db, study, study["hidden"])
    client = login_as(study["patient"])
    for path in _paths(hidden) + [f"/api/reports/window/{study['hidden'].id}"]:
        assert client.get(path).status_code == 404, path


def test_reports_off_means_no_reports_through_the_api(study, login_as, db):
    summary = _report(db, study, study["pilot"])
    db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id, enable_nlp_report=False))
    db.session.commit()
    client = login_as(study["patient"])
    assert client.get("/api/reports/").get_json() == []
    for path in _paths(summary) + [f"/api/reports/window/{study['pilot'].id}"]:
        assert client.get(path).status_code == 404, path


def test_live_reports_are_for_the_research_team(study, login_as):
    assert login_as(study["patient"]).get(f"/api/reports/live/{study['pilot'].id}").status_code == 403
