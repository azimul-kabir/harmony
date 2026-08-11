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
    assert "/static/js/library.js?v=" in response.text
    assert "-forget-missing" in response.text


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
    assert 'id="metadata-manual-form"' in response.text
    assert 'id="metadata-preview-manual"' in response.text
    assert 'id="metadata-apply-manual"' in response.text
    assert 'id="metadata-artwork-file"' in response.text
    assert 'id="metadata-artwork-remove"' in response.text
    assert 'id="library-duplicates-open"' in response.text
    assert 'id="duplicate-review-dialog"' in response.text
    assert 'class="library-search-help"' in response.text
    assert 'data-search-example="is:duplicate"' in response.text
    assert 'id="metadata-provider"' in response.text
    assert '<option value="spotify">Spotify</option>' in response.text
