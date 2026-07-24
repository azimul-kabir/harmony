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
