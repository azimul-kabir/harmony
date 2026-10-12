from app.core.config import Settings
from app.core import version


def test_release_tag_is_used_for_app_version_and_ignores_app_version_env(
    tmp_path, monkeypatch
):
    release_tag_file = tmp_path / ".release-tag"
    release_tag_file.write_text("v3.2.0", encoding="utf-8")
    monkeypatch.setattr(version, "RELEASE_TAG_FILE", release_tag_file)
    monkeypatch.setenv("APP_VERSION", "3.0.0")

    settings = Settings(_env_file=None)

    assert settings.app_version == "3.2.0"


def test_local_app_version_comes_from_project_metadata(tmp_path, monkeypatch):
    project_file = tmp_path / "pyproject.toml"
    project_file.write_text('[project]\nname = "harmony"\nversion = "3.2.0"\n')
    monkeypatch.setattr(version, "RELEASE_TAG_FILE", tmp_path / "missing-tag")
    monkeypatch.setattr(version, "PROJECT_FILE", project_file)

    assert version.get_app_version() == "3.2.0"
