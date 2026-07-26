from fastapi.testclient import TestClient

from app.main import app


def test_library_health_exposes_job_diagnostics_dialog():
    response = TestClient(app).get(
        "/library/health?job_status=attention&job_type=library_bulk"
    )

    assert response.status_code == 200
    assert 'id="library-jobs-description"' in response.text
    assert 'id="library-job-dialog"' in response.text
    assert 'id="library-job-summary"' in response.text
    assert 'id="library-job-failures"' in response.text
    assert 'id="metadata-repair-provider"' in response.text
    assert 'id="metadata-repair-selected"' in response.text
    assert 'id="metadata-repair-count"' in response.text


def test_metadata_repair_batch_requires_a_bounded_issue_selection():
    response = TestClient(app).post(
        "/api/metadata/discoveries/health-issues",
        json={"issue_ids": [], "provider": "musicbrainz"},
    )
    assert response.status_code == 422
