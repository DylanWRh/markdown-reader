# Local Markdown Reader

[简体中文](README-zh.md)

A local-first documentation browser for Markdown projects.

Turn any Markdown repository into a browsable documentation workspace — without deployment, online services, or additional configuration.

## Why

Markdown has become a common source format for:

* Research notes
* Technical documentation
* Open-source projects
* Project specifications
* Experiment logs
* Personal knowledge bases

Git provides excellent version control for these documents, but reading a Markdown project locally is often inconvenient:

* GitHub is designed for code hosting rather than focused reading
* VS Code is optimized for editing instead of documentation browsing
* Documentation websites require additional build and deployment steps

Local Markdown Reader provides a lightweight reading experience while keeping Markdown files as the source of truth.

```
Markdown files + Git
        |
        v
Local Markdown Reader
        |
        v
A browsable local documentation workspace
```

## Features

### Project-based Reading

* Browse an entire Markdown project from its directory structure
* Navigate documents through a project file tree
* Automatically open `README.md`, `index.md`, or the first available Markdown file
* Keep relative links and local assets working naturally

### Rich Markdown Rendering

Supports:

* GitHub-style Markdown
* Code syntax highlighting
* Tables, task lists, and footnotes
* Mermaid diagrams
* MathJax mathematical expressions
* Local images and SVG assets

### Comfortable Reading Experience

Provides:

* Three-column documentation layout
* File search and navigation
* Breadcrumbs and table of contents
* Internal link preview and navigation
* Reading progress tracking
* Estimated reading time
* Collapsible sections
* Print-friendly styles

### Lightweight Editing (Optional)

Reading is the primary workflow, but lightweight editing is also supported:

* Edit Markdown source directly
* Save or discard changes
* Detect external file modifications
* Prevent accidental overwrites

## Use Cases

### Research Projects

Markdown is often used as the working format for research projects:

```
project/
├── README.md
├── proposal.md
├── experiments/
│   ├── exp1.md
│   └── exp2.md
└── notes/
    └── ideas.md
```

Open the repository as a structured research document.

### Open-source Projects

For repositories containing:

```
repository/
├── README.md
├── docs/
├── tutorials/
└── examples/
```

Local Markdown Reader provides a documentation-style browsing experience without building a documentation website.

### Personal Knowledge Bases

Keep notes as Markdown files managed by Git while enjoying a cleaner reading interface.

## Installation

Requirements:

* Python 3.10+

Install from source:

```bash
python -m pip install .
```

For development:

```bash
python -m pip install -e .
```

## Usage

Open a workspace:

```bash
readmd <directory>
```

Or select a workspace from the browser:

```bash
readmd
```

Open a specific initial document:

```bash
readmd <directory> --initial <markdown-file>
```

Additional options:

```bash
readmd <directory> --port 9000 --no-browser
```

## Design Philosophy

### Local-first

Your documents stay on your machine.

### Source-first

Markdown files remain the canonical source. The reader only provides a better presentation layer.

### Project-first

A Markdown project is more than a single file. The reader treats the whole directory as a connected documentation space.

## Privacy

* Runs locally by default
* Binds to `127.0.0.1`
* Only accesses the selected workspace
* Does not upload document contents
