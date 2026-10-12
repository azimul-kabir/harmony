from pathlib import Path
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RELEASE_TAG_FILE = PROJECT_ROOT / ".release-tag"
PROJECT_FILE = PROJECT_ROOT / "pyproject.toml"


def get_app_version() -> str:
    """Return the embedded release tag, or the project version for local builds."""
    if RELEASE_TAG_FILE.is_file():
        release_tag = RELEASE_TAG_FILE.read_text(encoding="utf-8").strip()
        if release_tag:
            return release_tag.removeprefix("v")

    with PROJECT_FILE.open("rb") as project_file:
        project = tomllib.load(project_file)
    return project["project"]["version"]
