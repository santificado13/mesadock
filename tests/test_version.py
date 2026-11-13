"""Release hygiene: version, metadata and documentation stay in sync."""
from __future__ import annotations

from pathlib import Path

import mesadock

ROOT = Path(__file__).resolve().parent.parent


def test_version_looks_like_semver():
    parts = mesadock.__version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)


def test_pyproject_version_matches_the_package():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "' + mesadock.__version__ + '"' in text


def test_readme_mentions_the_app_and_the_version_lineage():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert mesadock.APP_NAME in readme
    assert "pip install -r requirements.txt" in readme


def test_readme_documents_the_shortcuts_it_claims():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for shortcut in ("Ctrl+Shift+M", "Ctrl+Shift+D", "Esc"):
        assert shortcut in readme


def test_license_file_exists_and_is_mit():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License")


def test_requirements_pin_the_runtime_dependencies():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "pillow" in requirements


def test_no_reference_assets_are_shipped_as_app_artwork():
    assets = ROOT / "mesadock" / "assets"
    for name in ("mesadock.ico", "logo.png"):
        assert (assets / name).exists()
    reference = ROOT / "docs" / "ref"
    if reference.exists():
        # reference material must live outside the package
        assert reference.parent.name == "docs"


def test_the_package_declares_every_subpackage():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'include = ["mesadock*"]' in text
    assert "[tool.setuptools.package-data]" in text
