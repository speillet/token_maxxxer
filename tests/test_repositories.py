import json
import stat

import pytest

from token_maxxxer.repositories import (
    discover_repositories,
    load_history,
    local_path,
    remember_repository,
    repository_root,
    repository_suggestions,
)


def test_local_paths_urls_and_exact_repository_roots(repository) -> None:
    assert local_path(repository.as_uri()) == repository
    assert repository_root(repository) == repository
    child = repository / "child"
    child.mkdir()
    with pytest.raises(ValueError, match="root"):
        repository_root(child)
    assert repository_root(child, exact=False) == repository


@pytest.mark.parametrize(
    "value",
    [
        "https://github.com/example/repo",
        "file://server/repo",
        "file:///tmp/repo?secret=value",
        "file:///tmp/repo#fragment",
    ],
)
def test_remote_or_ambiguous_urls_are_rejected(value) -> None:
    with pytest.raises(ValueError):
        local_path(value)


def test_bounded_discovery_skips_symlinks_and_nested_repository_contents(
    repository, tmp_path
) -> None:
    (tmp_path / "linked").symlink_to(repository, target_is_directory=True)
    assert discover_repositories((tmp_path,)) == [repository]
    assert discover_repositories((tmp_path,), depth=0) == []
    assert discover_repositories((repository,), depth=0) == [repository]


def test_history_is_private_recent_first_and_deduplicated(
    repository, tmp_path, monkeypatch
) -> None:
    state = tmp_path / "state"
    assert load_history(state).repositories == ()
    assert not state.exists()
    remember_repository(state, repository, "builtin:improve-code")
    remember_repository(state, repository, "builtin:code-review")
    history = load_history(state)
    assert len(history.repositories) == 1
    assert history.repositories[0].skill == "builtin:code-review"
    assert stat.S_IMODE((state / "history.json").stat().st_mode) == 0o600
    monkeypatch.chdir(tmp_path)
    assert repository_suggestions((tmp_path,), (repository,), history) == [repository]


def test_invalid_history_is_not_overwritten(repository, tmp_path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    path = state / "history.json"
    path.write_text(json.dumps({"schema_version": 2, "repositories": []}))
    previous = path.read_bytes()
    with pytest.raises(ValueError):
        remember_repository(state, repository, "builtin:improve-code")
    assert path.read_bytes() == previous
