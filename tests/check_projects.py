from __future__ import annotations

import sys
from pathlib import Path


READER_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = READER_ROOT.parent
sys.path.insert(0, str(READER_ROOT))

from markdown_reader import ReaderConfig, find_initial_markdown, render_document  # noqa: E402


def main() -> None:
    for project_name in ("AgentSurvey", "AgentGraphics-Survey"):
        root = WORKSPACE / project_name
        config = ReaderConfig(root, find_initial_markdown(root))
        documents = list(root.rglob("*.md"))
        rendered = [
            render_document(config, document.relative_to(root).as_posix())
            for document in documents
        ]
        heading_count = sum(len(document["toc"]) for document in rendered)
        print(
            f"{project_name}: rendered {len(rendered)} files and "
            f"indexed {heading_count} headings"
        )


if __name__ == "__main__":
    main()
