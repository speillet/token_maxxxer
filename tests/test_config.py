from pathlib import Path

import pytest
from pydantic import ValidationError

from nightshift.config import Config, load_config
from nightshift.yaml_io import DocumentError, load_yaml


def configuration(tmp_path: Path) -> dict:
    return {
        "repositories": {"allowed": [str(tmp_path)]},
        "schedule": {"windows": [{"days": ["mon"], "start": "22:00", "end": "07:00"}]},
    }


def test_paths_are_relative_to_source_even_for_defaults(config_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(config_path.parent.parent)
    config = load_config(config_path)
    assert config.repositories.allowed == (config_path.parent,)
    assert config.storage.database == config_path.parent / "var/nightshift.sqlite"
    assert config.schedule.windows[0].duration_seconds() == 9 * 3600
    assert not (config_path.parent / "var").exists()


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("timezone", "Mars/Olympus", "fuseau IANA"),
        ("execution", {"concurrency": 2}, "concurrency"),
        ("execution", {"max_attempts_per_task": 0}, "max_attempts_per_task"),
        ("execution", {"retry_backoff_seconds": [30, 10]}, "croissants"),
        ("execution", {"retry_backoff_seconds": []}, "retry_backoff_seconds"),
        ("execution", {"task_timeout_minutes": True}, "task_timeout_minutes"),
        ("git", {"auto_merge": True}, "auto_merge"),
        ("authentication", {"reject_api_configuration": False}, "reject_api_configuration"),
        ("storage", {"database": "same", "checkpoints": "same"}, "distinctes"),
        ("unexpected", "secret-value", "Extra inputs"),
    ],
)
def test_invalid_config_is_rejected(tmp_path, key, value, message) -> None:
    data = configuration(tmp_path)
    data[key] = value
    with pytest.raises(ValidationError, match=message) as error:
        Config.model_validate(data)
    assert "secret-value" not in str(error.value)


@pytest.mark.parametrize(
    ("start", "end", "days"),
    [
        ("24:00", "07:00", ["mon"]),
        ("22:00", "22:00", ["mon"]),
        ("22:00", "07:00", ["mon", "mon"]),
        ("22:00", "07:00", ["monday"]),
    ],
)
def test_invalid_windows(tmp_path, start, end, days) -> None:
    data = configuration(tmp_path)
    data["schedule"] = {"windows": [{"days": days, "start": start, "end": end}]}
    with pytest.raises(ValidationError):
        Config.model_validate(data)


def test_allowlist_resolves_symlinks_and_rejects_duplicates(tmp_path) -> None:
    link = tmp_path / "alias"
    link.symlink_to(tmp_path, target_is_directory=True)
    data = configuration(tmp_path)
    data["repositories"] = {"allowed": [str(tmp_path), str(link)]}
    with pytest.raises(ValidationError, match="uniques"):
        Config.model_validate(data)


@pytest.mark.parametrize("content", ["a: 1\na: 2", "a: &x [1]\nb: *x", "!!python/object:os {}"])
def test_unsafe_or_ambiguous_yaml_is_rejected(tmp_path, content) -> None:
    path = tmp_path / "input.yaml"
    path.write_text(content)
    with pytest.raises(DocumentError):
        load_yaml(path)
