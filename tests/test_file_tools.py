import subprocess

import pytest

from token_maxxxer.file_tools import FileTools


def track(repository, *paths) -> None:
    subprocess.run(["git", "-C", str(repository), "add", "--", *paths], check=True)


def test_tools_read_only_tracked_text_and_redact_detected_credentials(repository) -> None:
    (repository / "secrets.py").write_text('api_key = "sk-fixture-private-value"\n')
    (repository / "binary.dat").write_bytes(b"\x00binary")
    (repository / "untracked.txt").write_text("Private untracked notes.")
    (repository / ".env").write_text("Private configuration.")
    track(repository, "secrets.py", "binary.dat")
    tools = FileTools(repository, editable=False)
    assert "print('hello')" in tools.read_file("main.py")
    assert "sk-fixture-private-value" not in tools.read_file("secrets.py")
    assert "Keep changes focused" in tools.repository_instructions()
    for value in (".env", "untracked.txt", "binary.dat"):
        with pytest.raises(ValueError):
            tools.read_file(value)
    with pytest.raises(ValueError, match="review"):
        tools.write_file("main.py", "changed")


def test_tracked_source_directories_with_generic_names_are_readable(repository) -> None:
    for directory in ("var", "worktrees"):
        (repository / "src" / directory).mkdir(parents=True)
        (repository / "src" / directory / "models.py").write_text("VALUE = 1\n")
        track(repository, f"src/{directory}/models.py")
    tools = FileTools(repository, editable=False)
    assert tools.read_file("src/var/models.py") == "VALUE = 1\n"
    assert "src/worktrees/models.py" in tools.list_files("src/")["files"]


@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        "/tmp/outside",
        ".git/config",
        ".GIT/HEAD",
        ".env",
        "nested/.env/key.txt",
        "private/data.txt",
        "credentials.json",
        "certificate.pem",
        "bad\x00path",
        "directory\\file.py",
    ],
)
def test_unsafe_writes_are_denied(repository, path) -> None:
    tools = FileTools(repository, editable=True)
    with pytest.raises(ValueError):
        tools.write_file(path, "Untrusted content.")


def test_edits_require_a_current_read_and_new_files_can_be_created(repository) -> None:
    tools = FileTools(repository, editable=True)
    with pytest.raises(ValueError, match="read"):
        tools.write_file("main.py", "print('changed')\n")
    tools.read_file("main.py")
    (repository / "main.py").write_text("Concurrent local edit.\n")
    with pytest.raises(ValueError, match="changed since"):
        tools.write_file("main.py", "print('changed')\n")
    tools.read_file("main.py")
    tools.write_file("main.py", "print('changed')\n")
    tools.write_file("tests/test_main.py", "def test_main():\n    assert True\n")
    assert tools.write_version == 2
    assert tools.changed == {"main.py", "tests/test_main.py"}
    assert "tests/test_main.py" in tools.list_files("tests/")["files"]


def test_symlinks_ignored_paths_and_existing_untracked_files_are_denied(
    repository, tmp_path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("Private outside file.")
    (repository / "linked").symlink_to(outside, target_is_directory=True)
    (repository / "linked.py").symlink_to(outside / "secret.txt")
    (repository / "untracked.txt").write_text("Keep this.")
    track(repository, "linked", "linked.py")
    tools = FileTools(repository, editable=True)
    assert "linked.py" not in tools.catalog
    for name in ("linked/new.txt", "linked.py", "ignored.txt", "untracked.txt"):
        with pytest.raises(ValueError):
            tools.write_file(name, "Do not write.")
    assert (outside / "secret.txt").read_text() == "Private outside file."
    assert not (outside / "new.txt").exists()
    assert (repository / "untracked.txt").read_text() == "Keep this."


def test_skill_supporting_resources_stay_within_selected_directory(repository, tmp_path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "guide.md").write_text("Additional instructions.")
    (skill / "linked.md").symlink_to(repository / "readme.md")
    tools = FileTools(repository, editable=False, skill_directory=skill)
    assert tools.read_skill_file("guide.md") == "Additional instructions."
    for name in ("../repository/readme.md", "linked.md"):
        with pytest.raises(ValueError):
            tools.read_skill_file(name)


def test_detected_credentials_are_not_overwritten(repository) -> None:
    (repository / "secret.py").write_text('api_key = "sk-fixture-private-value"\n')
    track(repository, "secret.py")
    tools = FileTools(repository, editable=True)
    tools.read_file("secret.py")
    with pytest.raises(ValueError, match="credentials"):
        tools.write_file("secret.py", "api_key = 'redacted'\n")


def test_ignored_tracked_files_are_not_exposed(repository) -> None:
    (repository / "ignored.txt").write_text("Do not send this file.")
    subprocess.run(["git", "-C", str(repository), "add", "--force", "ignored.txt"], check=True)
    tools = FileTools(repository, editable=False)
    assert "ignored.txt" not in tools.catalog
    with pytest.raises(ValueError):
        tools.read_file("ignored.txt")
