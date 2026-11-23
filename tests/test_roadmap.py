import pytest

from token_maxxxer.roadmap import mark_done, parse_roadmap, ready_items

ROADMAP = """# Roadmap — demo

Intro text with a stray box that is not part of a milestone heading:

- [x] Bootstrap the repository.

## 1 — Foundation

- [x] Lock dependencies.
- [ ] Validate configuration.
  Reject unknown fields and report the path.
- [ ] Add a parser.
  - [x] Parse headings.
  - [ ] Parse checkboxes.
    - [ ] Support numbered lists.
* [ ] Document the parser.

```markdown
- [ ] An example inside a fence is not work.
```

## 2 — Delivery ##

1. [ ] Ship a release.
1. [X] Write the changelog.
"""


def test_milestones_items_and_states_follow_document_order():
    milestones = parse_roadmap(ROADMAP)
    assert [milestone.title for milestone in milestones] == [
        "Roadmap — demo",
        "1 — Foundation",
        "2 — Delivery",
    ]
    foundation = milestones[1]
    assert [(item.text, item.done) for item in foundation.items] == [
        ("Lock dependencies.", True),
        ("Validate configuration.", False),
        ("Add a parser.", False),
        ("Parse headings.", True),
        ("Parse checkboxes.", False),
        ("Support numbered lists.", False),
        ("Document the parser.", False),
    ]
    assert foundation.items[1].details == "Reject unknown fields and report the path."
    texts = [item.text for milestone in milestones for item in milestone.items]
    assert not any("inside a fence" in text for text in texts)
    assert [(item.text, item.done) for item in milestones[2].items] == [
        ("Ship a release.", False),
        ("Write the changelog.", True),
    ]
    assert foundation.section.startswith("## 1 — Foundation")
    assert "## 2" not in foundation.section


def test_ready_items_schedule_sub_items_before_their_parents():
    ready = [item.text for item in ready_items(parse_roadmap(ROADMAP))]
    assert ready == [
        "Validate configuration.",
        "Support numbered lists.",
        "Document the parser.",
        "Ship a release.",
    ]
    parser = parse_roadmap(ROADMAP)[1].items[2]
    assert parser.open_children == 2 and not parser.ready
    numbered = parse_roadmap(ROADMAP)[1].items[5]
    assert numbered.parent == "Parse checkboxes."


def test_keys_are_stable_unique_and_change_with_wording():
    first = parse_roadmap(ROADMAP)
    second = parse_roadmap(ROADMAP.replace("Intro text", "Changed intro"))
    keys = [item.key for milestone in first for item in milestone.items]
    assert len(set(keys)) == len(keys)
    assert keys == [item.key for milestone in second for item in milestone.items]
    reworded = parse_roadmap(ROADMAP.replace("Document the parser.", "Document parsing."))
    assert reworded[1].items[-1].key != first[1].items[-1].key
    duplicate = parse_roadmap("## M\n- [ ] Same.\n- [ ] Same.\n")
    assert duplicate[0].items[0].key != duplicate[0].items[1].key


def test_mark_done_checks_exactly_one_item_and_detects_drift():
    item = parse_roadmap(ROADMAP)[1].items[1]
    updated = mark_done(ROADMAP, item)
    assert updated is not None
    assert "- [x] Validate configuration." in updated
    assert updated.count("[x]") == ROADMAP.count("[x]") + 1
    assert mark_done(updated, item) is None
    numbered = parse_roadmap(ROADMAP)[2].items[0]
    assert "1. [x] Ship a release." in (mark_done(ROADMAP, numbered) or "")


def test_preamble_without_items_and_windows_line_endings():
    milestones = parse_roadmap("# Title\r\n\r\nText.\r\n\r\n## Next\r\n- [ ] Work.\r\n")
    assert [milestone.title for milestone in milestones] == ["Next"]
    item = milestones[0].items[0]
    assert mark_done("# Title\r\n\r\nText.\r\n\r\n## Next\r\n- [ ] Work.\r\n", item) == (
        "# Title\r\n\r\nText.\r\n\r\n## Next\r\n- [x] Work.\r\n"
    )


def test_oversized_roadmap_is_rejected():
    with pytest.raises(ValueError, match="too large"):
        parse_roadmap("- [ ] x\n" * 100_000)
