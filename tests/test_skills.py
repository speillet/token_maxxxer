from pathlib import Path

import pytest

from token_maxxxer.skills import discover_skills, load_skill, select_skill


def skill_file(base: Path, name: str, body: str = "Inspect tests before editing.") -> Path:
    path = base / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\nname: {name}\ndescription: Improve test coverage.\n---\n{body}\n")
    return path


def test_repository_skills_take_precedence_and_explicit_selection_is_supported(
    repository, tmp_path, monkeypatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    local = skill_file(repository / ".agents/skills", "test-review")
    skill_file(home / ".codex/skills", "test-review")
    catalog = discover_skills(repository)
    assert select_skill(catalog, "auto", mode="edit").path == local
    assert select_skill(catalog, "user:test-review", mode="edit").id == "user:test-review"
    assert select_skill(catalog, str(local), mode="edit").path == local
    with pytest.raises(ValueError, match="ambiguous"):
        select_skill(catalog, "test-review", mode="edit")


def test_unrelated_user_skill_is_not_automatically_selected(
    repository, tmp_path, monkeypatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    skill_file(home / ".agents/skills", "deploy-production")
    catalog = discover_skills(repository)
    assert select_skill(catalog, None, mode="edit").id == "builtin:improve-code"
    assert select_skill(catalog, None, mode="review").id == "builtin:code-review"


@pytest.mark.parametrize(
    "header",
    [
        "name: one\nname: two",
        "description: [invalid]",
        "name: &name test\ndescription: *name",
        "name: bad name",
    ],
)
def test_invalid_skill_metadata_is_rejected_without_echoing_content(tmp_path, header) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(f"---\n{header}\n---\nPrivate instructions.\n")
    with pytest.raises(ValueError) as error:
        load_skill(path)
    assert "Private instructions" not in str(error.value)


def test_symlinked_and_oversized_skills_are_rejected(tmp_path) -> None:
    path = skill_file(tmp_path, "real")
    link = tmp_path / "SKILL.md"
    link.symlink_to(path)
    with pytest.raises(ValueError):
        load_skill(link)
    path.write_text("x" * 65_537)
    with pytest.raises(ValueError):
        load_skill(path)
