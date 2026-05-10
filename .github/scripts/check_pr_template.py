#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "markdown-it-py==4.2.0",
# ]
# ///

"""Check that a PR body follows the pull request template."""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode


TEMPLATE_PATH = Path(".github/PULL_REQUEST_TEMPLATE.md")


@dataclass(frozen=True)
class Heading:
    """A Markdown heading's level and text."""

    level: int
    text: str


@dataclass(frozen=True)
class HeadingSection:
    """A Markdown heading and the nodes in its section."""

    heading: Heading
    nodes: list[SyntaxTreeNode]


def fail(errors: str | list[str]) -> None:
    """Print GitHub Actions error annotations and exit."""
    if isinstance(errors, str):
        errors = [errors]

    for error in errors:
        print(f"::error::{error}")  # noqa: T201

    print(f"::error::Please fill out the PR template: {TEMPLATE_PATH}")
    sys.exit(1)


def read_pr_body() -> str:
    """Read the PR body from the GitHub Actions event payload."""
    event_path = Path(os.environ["GITHUB_EVENT_PATH"])
    event = json.loads(event_path.read_text(encoding="utf-8"))
    return event["pull_request"].get("body") or ""


def is_heading(node: SyntaxTreeNode) -> bool:
    """Return whether a Markdown node is a heading."""
    return node.type == "heading" and node.tag.startswith("h")


def parse_heading(node: SyntaxTreeNode) -> Heading:
    """Return a heading node's level and plain text."""
    return Heading(level=int(node.tag[1:]), text=node.children[0].content.strip())


def format_heading(heading: Heading) -> str:
    """Format a heading as Markdown."""
    return f"{'#' * heading.level} {heading.text}"


def collect_heading_sections(tree: SyntaxTreeNode) -> list[HeadingSection]:
    """Return all headings and their section nodes in document order."""
    sections: list[HeadingSection] = []
    nodes = tree.children

    for index, node in enumerate(nodes):
        if not is_heading(node):
            continue

        heading = parse_heading(node)
        section_nodes: list[SyntaxTreeNode] = []

        for next_node in nodes[index + 1 :]:
            if is_heading(next_node) and parse_heading(next_node).level <= heading.level:
                break
            section_nodes.append(next_node)

        sections.append(HeadingSection(heading=heading, nodes=section_nodes))

    return sections


def find_heading_section(
    sections: list[HeadingSection],
    heading: Heading,
    start: int = 0,
) -> int | None:
    """Return the index of a heading section, or None if it is not found."""
    for index in range(start, len(sections)):
        if sections[index].heading == heading:
            return index
    return None


def is_html_comment(node: SyntaxTreeNode) -> bool:
    """Return whether a node is an HTML comment."""
    content = node.content.strip()
    return (
        node.type in {"html_inline", "html_block"}
        and content.startswith("<!--")
        and content.endswith("-->")
    )


def node_has_content(node: SyntaxTreeNode) -> bool:
    """Return whether a node has non-comment, non-heading content."""
    if is_heading(node) or is_html_comment(node):
        return False

    for descendant in node.walk():
        if descendant.type == "root" or is_heading(descendant) or is_html_comment(descendant):
            continue
        if descendant.content.strip():
            return True

    return False


def section_has_content(section: HeadingSection) -> bool:
    """Return whether a heading section has non-comment body content."""
    return any(node_has_content(node) for node in section.nodes)


def check_required_sections(
    required_sections: list[HeadingSection],
    pr_sections: list[HeadingSection],
) -> list[str]:
    """Return errors for missing, out-of-order, or empty required sections."""
    errors: list[str] = []
    search_start = 0

    for required_section in required_sections:
        heading = required_section.heading
        index = find_heading_section(pr_sections, heading, search_start)

        if index is None:
            if find_heading_section(pr_sections, heading) is None:
                errors.append(
                    f"PR is missing required template heading: {format_heading(heading)}",
                )
            else:
                errors.append(
                    f"Required template heading is out of order: {format_heading(heading)}",
                )
            continue

        if not section_has_content(pr_sections[index]):
            errors.append(
                f"Section '{format_heading(heading)}' is empty. Please fill in this section.",
            )

        search_start = index + 1

    return errors


def main() -> None:
    """Run the PR template compliance check."""
    if not TEMPLATE_PATH.is_file():
        fail(f"Pull request template not found: {TEMPLATE_PATH}")

    pr_body = read_pr_body()
    if not pr_body.strip():
        fail("PR body is empty. Please use the pull request template.")

    md = MarkdownIt("commonmark")
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    template_sections = collect_heading_sections(SyntaxTreeNode(md.parse(template)))

    if not template_sections:
        fail(f"No headings found in {TEMPLATE_PATH}.")

    pr_sections = collect_heading_sections(SyntaxTreeNode(md.parse(pr_body)))
    errors = check_required_sections(template_sections, pr_sections)

    if pr_body.strip() == template.strip():
        errors.append("PR body is unchanged from the pull request template.")

    if errors:
        fail(["PR template is not properly filled out.", *errors])

    print("PR template compliance check passed.")  # noqa: T201


if __name__ == "__main__":
    main()
