"""Researcher media library: uploads, image cleaning, storage, and who can see what.

The rule under test: a researcher sees only their own media, a participant only
their own researcher's, admins everything; anyone else gets "not found".
"""
import io

import pytest
from PIL import Image

from llm_chat.extensions import db as _db
from llm_chat.media.store import S3Store
from llm_chat.models import MediaAsset, ProviderPatient

UPLOAD_HEADERS = {"X-Requested-With": "fetch"}
JSON_HEADERS = {"Content-Type": "application/json"}


def image_bytes(fmt="PNG", size=(64, 48), mode="RGB", **save_kwargs):
    out = io.BytesIO()
    color = (200, 80, 40) if mode in ("RGB", "RGBA") else 1
    Image.new(mode, size, color).save(out, fmt, **save_kwargs)
    return out.getvalue()


def upload(client, data, filename="ann.png", label="Ann", alt_text="Ann, smiling", headers=UPLOAD_HEADERS):
    return client.post("/api/provider/media", headers=headers, content_type="multipart/form-data",
                       data={"file": (io.BytesIO(data), filename), "label": label, "alt_text": alt_text})


@pytest.fixture
def media_dir(app, tmp_path):
    app.config["MEDIA_LOCAL_DIR"] = str(tmp_path)
    app.extensions.pop("cloze_media_store", None)
    return tmp_path


@pytest.fixture
def people(make_user):
    """Two researchers, each with a participant, and an admin."""
    a, b = make_user("prov_a", role="provider"), make_user("prov_b", role="provider")
    pa, pb = make_user("pt_a"), make_user("pt_b")
    _db.session.add_all([ProviderPatient(provider_id=a.id, patient_id=pa.id),
                         ProviderPatient(provider_id=b.id, patient_id=pb.id)])
    _db.session.commit()
    return {"a": a, "b": b, "pa": pa, "pb": pb, "admin": make_user("root", role="admin")}


@pytest.fixture
def asset_id(media_dir, people, login_as):
    resp = upload(login_as(people["a"]), image_bytes())
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["id"]


# ── Who can see what ─────────────────────────────────────────


@pytest.mark.parametrize("who, status", [
    ("a", 200),       # the owner
    ("pa", 200),      # the owner's participant
    ("admin", 200),
    ("b", 404),       # another researcher
    ("pb", 404),      # another researcher's participant
])
@pytest.mark.parametrize("rendition", ["", "?r=thumb"])
def test_media_is_served_only_to_its_owner_their_participants_and_admins(
        login_as, people, asset_id, who, status, rendition):
    resp = login_as(people[who]).get(f"/media/{asset_id}{rendition}")
    assert resp.status_code == status
    if status == 200:
        assert resp.mimetype == "image/webp"
        assert "private" in resp.headers["Cache-Control"]


def test_media_needs_sign_in(client, asset_id):
    from flask import g
    g.pop("_login_user", None)  # forget the uploader (tests share one app context)
    resp = client.get(f"/media/{asset_id}")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


@pytest.mark.parametrize("path", ["not-a-uuid", "00000000-0000-0000-0000-000000000000"])
def test_unknown_media_is_not_found(login_as, people, media_dir, path):
    assert login_as(people["admin"]).get(f"/media/{path}").status_code == 404


def test_unknown_rendition_is_not_found(login_as, people, asset_id):
    c = login_as(people["a"])
    assert c.get(f"/media/{asset_id}?r=original").status_code == 404
    assert c.get(f"/media/{asset_id}?r=../../etc/passwd").status_code == 404


def test_library_lists_only_your_own_media(login_as, people, asset_id):
    mine = login_as(people["a"]).get("/api/provider/media").get_json()
    theirs = login_as(people["b"]).get("/api/provider/media").get_json()
    assert [a["id"] for a in mine["assets"]] == [asset_id]
    assert theirs["assets"] == []
    assert login_as(people["pa"]).get("/api/provider/media").status_code == 403


def test_other_researchers_cannot_edit_or_remove_your_media(login_as, people, asset_id):
    b = login_as(people["b"])
    assert b.patch(f"/api/provider/media/{asset_id}", json={"label": "mine now"}).status_code == 404
    assert b.delete(f"/api/provider/media/{asset_id}", headers=JSON_HEADERS).status_code == 404
    asset = MediaAsset.query.filter_by(public_id=asset_id).one()
    assert asset.label == "Ann" and asset.deleted_at is None


def test_owner_can_rename_and_describe(login_as, people, asset_id):
    resp = login_as(people["a"]).patch(f"/api/provider/media/{asset_id}",
                                       json={"label": "Ann (v2)", "alt_text": "Ann waving"})
    assert resp.status_code == 200
    assert resp.get_json()["label"] == "Ann (v2)"
    assert resp.get_json()["alt_text"] == "Ann waving"


def test_removed_media_leaves_the_library_but_still_shows_where_used(login_as, people, asset_id):
    a = login_as(people["a"])
    assert a.delete(f"/api/provider/media/{asset_id}", headers=JSON_HEADERS).status_code == 200
    assert a.get("/api/provider/media").get_json()["assets"] == []
    assert login_as(people["pa"]).get(f"/media/{asset_id}").status_code == 200


# ── Uploads ──────────────────────────────────────────────────


def stored_display(asset_id):
    asset = MediaAsset.query.filter_by(public_id=asset_id).one()
    return asset, asset.rendition("display")


@pytest.mark.parametrize("fmt, mode", [("PNG", "RGBA"), ("JPEG", "RGB"), ("WEBP", "RGB")])
def test_png_jpeg_and_webp_are_stored_as_webp(login_as, people, media_dir, fmt, mode):
    resp = upload(login_as(people["a"]), image_bytes(fmt, mode=mode), filename=f"x.{fmt.lower()}")
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["kind"] == "image" and body["status"] == "ready"
    assert (body["width"], body["height"]) == (64, 48)
    asset, display = stored_display(body["id"])
    assert display.content_type == "image/webp"
    assert display.storage_key == f"media/{people['a'].id}/{body['id']}/display.webp"
    assert Image.open(media_dir / display.storage_key).format == "WEBP"
    assert {r.role for r in asset.renditions} == {"display", "thumb"}


def test_large_images_are_shrunk(login_as, people, media_dir):
    body = upload(login_as(people["a"]), image_bytes("JPEG", size=(3000, 1500))).get_json()
    asset, display = stored_display(body["id"])
    assert (display.width, display.height) == (2048, 1024)
    assert max(asset.rendition("thumb").width, asset.rendition("thumb").height) == 320


def test_metadata_and_appended_data_are_stripped(login_as, people, media_dir):
    exif = Image.Exif()
    exif[0x010E] = "SECRET-EXIF-DESCRIPTION"            # ImageDescription
    exif.get_ifd(0x8825)[2] = (42.0, 21.0, 7.0)          # GPSLatitude
    jpeg = image_bytes("JPEG", exif=exif.tobytes())
    payload = jpeg + b"<script>alert(1)</script>"
    assert b"SECRET-EXIF" in payload

    body = upload(login_as(people["a"]), payload, filename="photo.jpg").get_json()
    for rendition in MediaAsset.query.filter_by(public_id=body["id"]).one().renditions:
        stored = (media_dir / rendition.storage_key).read_bytes()
        assert b"SECRET-EXIF" not in stored and b"<script>" not in stored
        img = Image.open(io.BytesIO(stored))
        assert not img.getexif()
        assert "xmp" not in img.info and "exif" not in img.info


def test_original_filename_is_kept_for_display_only(login_as, people, media_dir):
    body = upload(login_as(people["a"]), image_bytes(), filename="../../evil name.png", label="").get_json()
    assert body["original_filename"] == "evil name.png"
    assert body["label"] == "evil name"
    assert "evil" not in stored_display(body["id"])[1].storage_key


@pytest.mark.parametrize("data, filename", [
    (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "x.svg"),
    (b"<html><script>alert(1)</script></html>", "x.png"),
    (image_bytes("GIF", mode="P"), "x.gif"),
    (b"", "x.png"),
])
def test_non_images_and_other_formats_are_refused(login_as, people, media_dir, data, filename):
    resp = upload(login_as(people["a"]), data, filename=filename)
    assert resp.status_code == 400
    assert MediaAsset.query.count() == 0


def test_decompression_bombs_are_refused_unopened(login_as, people, media_dir):
    bomb = image_bytes("PNG", size=(8000, 6000), mode="1")   # 48 megapixels, a few KB
    assert len(bomb) < 100_000
    resp = upload(login_as(people["a"]), bomb)
    assert resp.status_code == 400
    assert "megapixels" in resp.get_json()["error"]


def test_pixel_limits_admit_phone_photos_but_not_huge_pngs(login_as, people, media_dir):
    c = login_as(people["a"])
    # JPEGs decode at reduced scale, so a 24-megapixel phone photo is fine...
    photo = upload(c, image_bytes("JPEG", size=(5712, 4284), mode="L"), filename="photo.jpg")
    assert photo.status_code == 201
    assert (photo.get_json()["width"], photo.get_json()["height"]) == (2048, 1536)
    # ...but PNG and WebP decode at full size, so they're held to 16 megapixels.
    resp = upload(c, image_bytes("PNG", size=(5000, 4000), mode="1"))
    assert resp.status_code == 400
    assert "16 megapixels" in resp.get_json()["error"]


def test_photos_are_turned_upright(login_as, people, media_dir):
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90° clockwise to display
    body = upload(login_as(people["a"]), image_bytes("JPEG", size=(64, 48), exif=exif.tobytes()),
                  filename="sideways.jpg").get_json()
    assert (body["width"], body["height"]) == (48, 64)


def test_oversized_uploads_are_refused(login_as, people, media_dir):
    resp = upload(login_as(people["a"]), b"\0" * (10 * 1024 * 1024 + 1))
    assert resp.status_code == 413


def test_participants_cannot_upload(login_as, people, media_dir):
    assert upload(login_as(people["pa"]), image_bytes()).status_code == 403


def test_uploads_need_the_same_site_header(login_as, people, media_dir):
    # Another site can post a multipart form, but can't add this header.
    assert upload(login_as(people["a"]), image_bytes(), headers={}).status_code == 415


def multipart_body(data):
    return (b'--X\r\nContent-Disposition: form-data; name="file"; filename="a.png"\r\n'
            b"Content-Type: image/png\r\n\r\n" + data + b"\r\n--X--\r\n")


@pytest.mark.parametrize("content_type", [
    "MULTIPART/FORM-DATA; boundary=X; x=application/json",
    "Multipart/Form-Data; boundary=X",
])
def test_content_type_case_cannot_skip_the_header(login_as, people, media_dir, content_type):
    resp = login_as(people["a"]).post("/api/provider/media", data=multipart_body(image_bytes()),
                                      headers={"Content-Type": content_type})
    assert resp.status_code == 415
    assert MediaAsset.query.count() == 0


def test_uploads_are_off_in_production_without_a_bucket(app, login_as, people):
    app.config["PRODUCTION"] = True
    app.extensions.pop("cloze_media_store", None)
    c = login_as(people["a"])
    assert c.get("/api/provider/media").get_json()["uploads_enabled"] is False
    resp = upload(c, image_bytes())
    assert resp.status_code == 503
    assert MediaAsset.query.count() == 0


# ── S3 ───────────────────────────────────────────────────────


@pytest.fixture
def s3(app):
    import boto3
    from botocore.config import Config
    from botocore.stub import Stubber
    client = boto3.client("s3", region_name="us-east-1", aws_access_key_id="AKIATESTTESTTESTTEST",
                          aws_secret_access_key="test-secret",
                          config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}))
    app.extensions["cloze_media_store"] = S3Store("cloze-test-media", client)
    with Stubber(client) as stubber:
        yield stubber


def test_s3_upload_and_presigned_redirect(login_as, people, s3):
    from botocore.stub import ANY
    for role in ("display", "thumb"):
        s3.add_response("put_object", {}, {
            "Bucket": "cloze-test-media", "Key": ANY, "Body": ANY,
            "ContentType": "image/webp", "CacheControl": "private, max-age=300",
        })
    resp = upload(login_as(people["a"]), image_bytes())
    assert resp.status_code == 201
    s3.assert_no_pending_responses()
    asset_id = resp.get_json()["id"]

    resp = login_as(people["pa"]).get(f"/media/{asset_id}")
    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location.startswith("https://cloze-test-media.s3.amazonaws.com/")
    assert f"media/{people['a'].id}/{asset_id}/display.webp" in location
    assert "X-Amz-Signature=" in location and "X-Amz-Expires=600" in location
    assert resp.headers["Cache-Control"] == "private, max-age=300"

    # Another researcher's participant gets no URL at all.
    assert login_as(people["pb"]).get(f"/media/{asset_id}").status_code == 404


def test_s3_failure_stores_nothing(login_as, people, s3):
    s3.add_client_error("put_object", service_error_code="AccessDenied", http_status_code=403)
    resp = upload(login_as(people["a"]), image_bytes())
    assert resp.status_code == 502
    assert MediaAsset.query.count() == 0
