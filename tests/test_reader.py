from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from markdown_reader import (  # noqa: E402
    ReaderConfig,
    create_app,
    find_initial_markdown,
    render_document,
)


class ReaderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        (self.root / "chapters").mkdir()
        (self.root / "assets").mkdir()
        (self.root / "README.md").write_text(
            "# Home\n\n## [Linked heading](chapters/one.md)\n\n[Chapter](chapters/one.md#details)\n",
            encoding="utf-8",
        )
        (self.root / "chapters" / "one.md").write_text(
            """# One

## Details

Inline $x^2$ and:

$$
y = x + 1
$$

```mermaid
flowchart LR
  A --> B
```

![Diagram](../assets/example.svg)
""",
            encoding="utf-8",
        )
        (self.root / "assets" / "example.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8"
        )
        app = create_app(ReaderConfig(self.root, self.root / "README.md"))
        app.testing = True
        self.client = app.test_client()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_document_features_are_rendered_and_rewritten(self) -> None:
        data = render_document(
            ReaderConfig(self.root, self.root / "README.md"), "chapters/one.md"
        )
        self.assertEqual(data["title"], "One")
        self.assertEqual(data["toc"][1]["id"], "details")
        self.assertIn('class="mermaid"', data["html"])
        self.assertIn('class="math block"', data["html"])
        self.assertIn(r"\[y = x + 1\]", data["html"])
        self.assertIn(r"\(x^2\)", data["html"])
        self.assertIn("/api/raw?path=assets/example.svg", data["html"])

    def test_internal_links_are_previewable(self) -> None:
        response = self.client.get("/api/document?path=README.md")
        self.assertEqual(response.status_code, 200)
        rendered = response.get_json()["html"]
        self.assertIn('id="linked-heading"', rendered)
        self.assertIn('data-doc-path="chapters/one.md"', rendered)
        self.assertIn('data-anchor="details"', rendered)

        preview = self.client.get("/api/preview?path=chapters/one.md&anchor=details")
        self.assertEqual(preview.status_code, 200)
        self.assertIn("Details", preview.get_json()["html"])

    def test_project_boundary_is_enforced(self) -> None:
        self.assertEqual(self.client.get("/api/raw?path=../outside.md").status_code, 404)
        self.assertEqual(self.client.get("/api/document?path=assets/example.svg").status_code, 404)

    def test_project_directory_prefers_readme(self) -> None:
        self.assertEqual(find_initial_markdown(self.root), (self.root / "README.md").resolve())

    def test_project_directory_falls_back_to_first_markdown(self) -> None:
        (self.root / "README.md").unlink()
        (self.root / "z-last.md").write_text("# Last", encoding="utf-8")
        (self.root / "a-first.md").write_text("# First", encoding="utf-8")
        self.assertEqual(find_initial_markdown(self.root), (self.root / "a-first.md").resolve())

    def test_initial_document_must_stay_in_project(self) -> None:
        with self.assertRaises(ValueError):
            find_initial_markdown(self.root, "../outside.md")


if __name__ == "__main__":
    unittest.main()
