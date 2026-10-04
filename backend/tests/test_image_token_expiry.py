"""Image bearer tokens: expired, wrong-image and missing tokens never serve a photo."""

from app.core.security import create_image_token
from tests.conftest import register
from tests.helpers import LOST_BACKPACK, make_image


def _upload(client, headers):
    rid = client.post("/reports", json=LOST_BACKPACK, headers=headers).json()["id"]
    r = client.post(f"/reports/{rid}/images", headers=headers, files={"file": ("x.png", make_image(fmt="PNG"), "image/png")})
    assert r.status_code == 201, r.text
    return r.json()


def test_valid_token_serves_the_photo(client):
    owner = register(client)
    image = _upload(client, owner)
    assert client.get(image["url"]).status_code == 200


def test_expired_token_is_refused(client):
    owner = register(client)
    image = _upload(client, owner)
    expired = create_image_token(image["id"], minutes=-1)
    assert client.get(f"/images/{image['id']}?token={expired}").status_code == 404


def test_token_issued_for_another_image_is_refused(client):
    owner = register(client)
    image = _upload(client, owner)
    other = create_image_token(image["id"] + 100)
    assert client.get(f"/images/{image['id']}?token={other}").status_code == 404


def test_missing_token_is_refused(client):
    owner = register(client)
    image = _upload(client, owner)
    assert client.get(f"/images/{image['id']}").status_code == 422
