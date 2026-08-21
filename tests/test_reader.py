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
from markdown_reader.app import parse_args  # noqa: E402


class ReaderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.state_file = self.root / ".reader-state" / "workspaces.json"
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
        app = create_app(
            ReaderConfig(self.root, self.root / "README.md"),
            state_file=self.state_file,
        )
        app.testing = True
        self.switch_token = app.config["WORKSPACE_SWITCH_TOKEN"]
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

    def test_raw_html_media_sources_are_rewritten(self) -> None:
        (self.root / "chapters" / "media.md").write_text(
            """# Media

<video controls src="../assets/demo.mp4" poster="../assets/poster.png">
  <source src="../assets/demo.webm" type="video/webm">
  <track src="../assets/captions.vtt" kind="captions">
</video>

Inline <audio src="../assets/demo.mp3"></audio> and <img src="../assets/raw.png">.

<video src="https://example.com/external.mp4"></video>
""",
            encoding="utf-8",
        )

        data = render_document(
            ReaderConfig(self.root, self.root / "README.md"), "chapters/media.md"
        )
        rendered = data["html"]

        self.assertIn('src="/api/raw?path=assets/demo.mp4"', rendered)
        self.assertIn('poster="/api/raw?path=assets/poster.png"', rendered)
        self.assertIn('src="/api/raw?path=assets/demo.webm"', rendered)
        self.assertIn('src="/api/raw?path=assets/captions.vtt"', rendered)
        self.assertIn('src="/api/raw?path=assets/demo.mp3"', rendered)
        self.assertIn('src="/api/raw?path=assets/raw.png"', rendered)
        self.assertIn('src="https://example.com/external.mp4"', rendered)

    def test_raw_video_endpoint_reports_the_media_type(self) -> None:
        (self.root / "assets" / "demo.mp4").write_bytes(b"video")

        response = self.client.head("/api/raw?path=assets/demo.mp4")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, "video/mp4")
        response.close()

        ranged = self.client.get(
            "/api/raw?path=assets/demo.mp4", headers={"Range": "bytes=1-3"}
        )
        self.assertEqual(ranged.status_code, 206)
        self.assertEqual(ranged.data, b"ide")
        ranged.close()

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

    def test_reader_page_includes_section_folding_control(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('id="toggleAllSections"', page)
        self.assertIn('aria-label="折叠全部章节"', page)

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

    def test_workspace_switch_requires_local_session_token(self) -> None:
        response = self.client.post("/api/workspace", json={"path": str(self.root)})
        self.assertEqual(response.status_code, 403)

    def test_edit_source_requires_local_session_token(self) -> None:
        self.assertEqual(self.client.get("/api/source?path=README.md").status_code, 403)
        self.assertEqual(
            self.client.put(
                "/api/source",
                json={
                    "path": "README.md",
                    "source": "# Changed",
                    "version": "unknown",
                    "workspace": str(self.root.resolve()),
                },
            ).status_code,
            403,
        )

    def test_markdown_source_can_be_loaded_and_saved(self) -> None:
        loaded = self.client.get(
            "/api/source?path=README.md",
            headers={"X-Workspace-Token": self.switch_token},
        )
        self.assertEqual(loaded.status_code, 200)
        source = loaded.get_json()
        self.assertIn("# Home", source["source"])
        self.assertEqual(source["workspace"], str(self.root.resolve()))

        changed = "# Updated\n\nSaved from the browser editor.\n"
        saved = self.client.put(
            "/api/source",
            headers={"X-Workspace-Token": self.switch_token},
            json={
                "path": source["path"],
                "source": changed,
                "version": source["version"],
                "workspace": source["workspace"],
            },
        )
        self.assertEqual(saved.status_code, 200)
        payload = saved.get_json()
        self.assertEqual((self.root / "README.md").read_text(encoding="utf-8"), changed)
        self.assertNotEqual(payload["version"], source["version"])
        self.assertEqual(payload["document"]["title"], "Updated")
        self.assertIn("Saved from the browser editor.", payload["document"]["html"])

    def test_save_rejects_external_modification(self) -> None:
        loaded = self.client.get(
            "/api/source?path=README.md",
            headers={"X-Workspace-Token": self.switch_token},
        ).get_json()
        external = "# Changed elsewhere\n"
        (self.root / "README.md").write_text(external, encoding="utf-8")

        response = self.client.put(
            "/api/source",
            headers={"X-Workspace-Token": self.switch_token},
            json={
                "path": loaded["path"],
                "source": "# Browser change\n",
                "version": loaded["version"],
                "workspace": loaded["workspace"],
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual((self.root / "README.md").read_text(encoding="utf-8"), external)

    def test_save_rejects_changed_workspace_identity(self) -> None:
        loaded = self.client.get(
            "/api/source?path=README.md",
            headers={"X-Workspace-Token": self.switch_token},
        ).get_json()
        loaded["workspace"] = str(self.root / "different")
        response = self.client.put(
            "/api/source",
            headers={"X-Workspace-Token": self.switch_token},
            json={
                "path": loaded["path"],
                "source": loaded["source"],
                "version": loaded["version"],
                "workspace": loaded["workspace"],
            },
        )
        self.assertEqual(response.status_code, 409)

    def test_edit_source_stays_inside_workspace(self) -> None:
        response = self.client.get(
            "/api/source?path=../outside.md",
            headers={"X-Workspace-Token": self.switch_token},
        )
        self.assertEqual(response.status_code, 404)

    def test_workspace_can_switch_and_enforces_new_boundary(self) -> None:
        second = self.root.parent / f"{self.root.name}-second"
        second.mkdir()
        self.addCleanup(lambda: second.rmdir() if second.exists() else None)
        (second / "README.md").write_text("# Second workspace", encoding="utf-8")

        response = self.client.post(
            "/api/workspace",
            json={"path": str(second)},
            headers={"X-Workspace-Token": self.switch_token},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["project"]["name"], second.name)
        self.assertEqual(data["project"]["initialFile"], "README.md")
        self.assertEqual(self.client.get("/api/document?path=README.md").status_code, 200)
        self.assertEqual(self.client.get("/api/raw?path=../outside.md").status_code, 404)
        self.assertEqual(data["recent"][0]["path"], str(second.resolve()))
        self.assertTrue(data["recent"][0]["current"])
        recents = self.client.get("/api/workspaces").get_json()["recent"]
        self.assertEqual([item["path"] for item in recents[:2]], [str(second.resolve()), str(self.root.resolve())])

        (second / "README.md").unlink()

    def test_workspace_switch_rejects_directory_without_markdown(self) -> None:
        empty = self.root / "empty-workspace"
        empty.mkdir()
        response = self.client.post(
            "/api/workspace",
            json={"path": str(empty)},
            headers={"X-Workspace-Token": self.switch_token},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("No Markdown files", response.get_json()["error"])

    def test_directory_browser_requires_local_session_token(self) -> None:
        self.assertEqual(self.client.get("/api/directories").status_code, 403)

    def test_directory_browser_lists_child_directories(self) -> None:
        response = self.client.get(
            f"/api/directories?path={self.root}",
            headers={"X-Workspace-Token": self.switch_token},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["path"], str(self.root.resolve()))
        self.assertTrue(data["hasMarkdown"])
        self.assertIn("chapters", [item["name"] for item in data["directories"]])

    def test_readmd_accepts_no_directory(self) -> None:
        self.assertIsNone(parse_args([]).directory)


class EmptyReaderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        app = create_app(None, state_file=self.root / "state.json", browse_start=self.root)
        app.testing = True
        self.token = app.config["WORKSPACE_SWITCH_TOKEN"]
        self.client = app.test_client()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_empty_reader_renders_initialization_page(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("选择一个工作区开始阅读", response.get_data(as_text=True))
        project = self.client.get("/api/project").get_json()
        self.assertFalse(project["initialized"])
        self.assertEqual(project["tree"], [])

    def test_empty_reader_blocks_document_access(self) -> None:
        self.assertEqual(self.client.get("/api/document?path=README.md").status_code, 409)

    def test_empty_reader_browses_from_launch_directory(self) -> None:
        (self.root / "notes").mkdir()
        response = self.client.get(
            "/api/directories",
            headers={"X-Workspace-Token": self.token},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["path"], str(self.root.resolve()))
        self.assertIn("notes", [item["name"] for item in data["directories"]])


if __name__ == "__main__":
    unittest.main()
