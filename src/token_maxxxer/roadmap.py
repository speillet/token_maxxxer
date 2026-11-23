"""Parse Markdown roadmap checklists into ordered milestones with stable item keys."""

import hashlib
import re
from dataclasses import dataclass, field

MAX_ROADMAP_BYTES = 524_288
MAX_SECTION_CHARACTERS = 6_000
MAX_DETAIL_CHARACTERS = 2_000
ROADMAP_CANDIDATES = ("ROADMAP.md", "docs/roadmap.md", "docs/ROADMAP.md", "roadmap.md")

_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
_ITEM = re.compile(r"^([ \t]*)(?:[-*+]|\d{1,9}[.)])[ \t]+\[([ xX])\][ \t]+(\S.*?)[ \t]*$")
_UNCHECKED = re.compile(r"^([ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+)\[ \]")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


@dataclass(frozen=True)
class RoadmapItem:
    key: str
    milestone: str
    text: str
    done: bool
    line: int
    raw: str
    details: str = ""
    parent: str = ""
    open_children: int = 0

    @property
    def ready(self) -> bool:
        """Open and not waiting for its own nested sub-items."""
        return not self.done and self.open_children == 0


@dataclass(frozen=True)
class Milestone:
    title: str
    section: str
    items: tuple[RoadmapItem, ...]

    @property
    def open_items(self) -> tuple[RoadmapItem, ...]:
        return tuple(item for item in self.items if not item.done)


@dataclass
class _Draft:
    indent: int
    done: bool
    text: str
    line: int
    raw: str
    milestone: int
    parent: int | None
    details: list[str] = field(default_factory=list)
    open_children: int = 0


def item_key(milestone: str, parent: str, text: str, occurrence: int = 0) -> str:
    """Identify an item by its wording and position, so a reworded item is new work."""
    source = f"{milestone}\n{parent}\n{text}\n{occurrence}"
    return f"roadmap:{hashlib.sha256(source.encode('utf-8')).hexdigest()[:16]}"


def parse_roadmap(content: str) -> tuple[Milestone, ...]:
    """Return milestones in document order; headings start milestones, checkboxes are items."""
    if len(content.encode("utf-8")) > MAX_ROADMAP_BYTES:
        raise ValueError("roadmap is too large (maximum 512 KiB)")
    lines = content.splitlines()
    titles: list[str] = ["Roadmap"]
    bounds: list[list[int]] = [[0, len(lines)]]
    drafts: list[_Draft] = []
    stack: list[tuple[int, int]] = []
    last: int | None = None
    fence = ""
    for index, line in enumerate(lines):
        fence_match = _FENCE.match(line)
        if fence:
            closing = line.strip()
            if set(closing) == {fence[0]} and len(closing) >= len(fence):
                fence = ""
            continue
        if fence_match:
            fence = fence_match.group(1)
            continue
        if heading := _HEADING.match(line):
            bounds[-1][1] = index
            titles.append(heading.group(2).strip())
            bounds.append([index, len(lines)])
            stack, last = [], None
            continue
        if item := _ITEM.match(line):
            indent = len(item.group(1).expandtabs(4))
            while stack and stack[-1][0] >= indent:
                stack.pop()
            drafts.append(
                _Draft(
                    indent=indent,
                    done=item.group(2) != " ",
                    text=item.group(3),
                    line=index,
                    raw=line,
                    milestone=len(titles) - 1,
                    parent=stack[-1][1] if stack else None,
                )
            )
            last = len(drafts) - 1
            stack.append((indent, last))
            continue
        if not line.strip():
            continue
        current_indent = len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip())
        if last is not None and current_indent > drafts[last].indent:
            drafts[last].details.append(line.strip())
        else:
            stack, last = [], None
    for draft in drafts:
        ancestor = draft.parent
        while not draft.done and ancestor is not None:
            drafts[ancestor].open_children += 1
            ancestor = drafts[ancestor].parent
    occurrences: dict[tuple[int, str, str], int] = {}
    items: list[list[RoadmapItem]] = [[] for _ in titles]
    for draft in drafts:
        parent = drafts[draft.parent].text if draft.parent is not None else ""
        identity = (draft.milestone, parent, draft.text)
        occurrence = occurrences.get(identity, 0)
        occurrences[identity] = occurrence + 1
        title = titles[draft.milestone]
        items[draft.milestone].append(
            RoadmapItem(
                key=item_key(title, parent, draft.text, occurrence),
                milestone=title,
                text=draft.text,
                done=draft.done,
                line=draft.line,
                raw=draft.raw,
                details="\n".join(draft.details)[:MAX_DETAIL_CHARACTERS],
                parent=parent,
                open_children=draft.open_children,
            )
        )
    return tuple(
        Milestone(
            title=title,
            section="\n".join(lines[start:end]).strip()[:MAX_SECTION_CHARACTERS],
            items=tuple(milestone_items),
        )
        for title, (start, end), milestone_items in zip(titles, bounds, items, strict=True)
        if milestone_items
    )


def ready_items(milestones: tuple[Milestone, ...]) -> list[RoadmapItem]:
    """Open items, earliest milestone first, nested sub-items before their parents."""
    return [item for milestone in milestones for item in milestone.items if item.ready]


def mark_done(content: str, item: RoadmapItem) -> str | None:
    """Check exactly the parsed item's box, or return None if the roadmap has changed."""
    lines = content.splitlines(keepends=True)
    if item.line >= len(lines) or lines[item.line].rstrip("\r\n") != item.raw:
        return None
    updated, count = _UNCHECKED.subn(r"\1[x]", lines[item.line], count=1)
    if count != 1:
        return None
    lines[item.line] = updated
    return "".join(lines)
