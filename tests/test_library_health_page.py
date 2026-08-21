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
    assert 'id="metadata-repair-provider"' not in response.text
    assert 'id="metadata-repair-selected"' not in response.text
    assert 'id="metadata-repair-count"' not in response.text
    assert 'id="metadata-analysis"' not in response.text
    assert 'id="metadata-issues-title"' not in response.text


def test_metadata_discovery_api_is_not_part_of_v3_surface():
    response = TestClient(app).post(
        "/api/metadata/discoveries/health-issues",
        json={"issue_ids": [], "provider": "musicbrainz"},
    )
    assert response.status_code == 404


def test_persisted_metadata_health_api_is_not_part_of_v3_surface():
    client = TestClient(app)

    assert client.get("/api/library/health/metadata/issues").status_code == 404
    assert client.post("/api/library/health/metadata/analyze").status_code == 404
