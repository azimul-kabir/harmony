from fastapi.testclient import TestClient

from app.main import app


def test_missing_review_exposes_forget_instead_of_file_delete():
    response = TestClient(app).get("/library?availability=missing")

    assert response.status_code == 200
    assert (
        'id="library-bulk-delete" class="library-bulk-delete" '
        'data-bulk-action="delete" hidden'
    ) in response.text
    assert (
        'id="library-bulk-forget-missing" class="library-bulk-delete" '
        'data-bulk-action="forget_missing" >'
    ) in response.text


def test_normal_library_exposes_file_delete_not_forget():
    response = TestClient(app).get("/library")

    assert response.status_code == 200
    assert (
        'id="library-bulk-delete" class="library-bulk-delete" '
        'data-bulk-action="delete" >'
    ) in response.text
    assert (
        'id="library-bulk-forget-missing" class="library-bulk-delete" '
        'data-bulk-action="forget_missing" hidden'
    ) in response.text
