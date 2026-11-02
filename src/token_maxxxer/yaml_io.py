"""Read trusted YAML without object constructors, duplicate keys or aliases."""

from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode
from yaml.tokens import AliasToken

MAX_YAML_BYTES = 1_048_576


class DocumentError(ValueError):
    """An invalid input document, safe to display without its contents."""


class UniqueSafeLoader(yaml.SafeLoader):
    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Any, Any]:
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                if key in mapping:
                    raise DocumentError("duplicate YAML key")
                mapping[key] = self.construct_object(value_node, deep=deep)
            except TypeError as exc:
                raise DocumentError("invalid YAML key") from exc
        return mapping


def load_yaml(path: Path) -> Any:
    with path.open("rb") as stream:
        raw = stream.read(MAX_YAML_BYTES + 1)
    if len(raw) > MAX_YAML_BYTES:
        raise DocumentError("YAML document is too large (maximum 1 MiB)")
    try:
        content = raw.decode("utf-8")
        if any(isinstance(token, AliasToken) for token in yaml.scan(content)):
            raise DocumentError("YAML aliases are not allowed")
        return yaml.load(content, Loader=UniqueSafeLoader)
    except (UnicodeError, yaml.YAMLError, RecursionError) as exc:
        raise DocumentError("invalid YAML document (expected UTF-8 and valid syntax)") from exc
