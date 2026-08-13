(() => {
  "use strict";

  const state = {
    project: null,
    currentPath: document.body.dataset.initialFile,
    currentAnchor: decodeURIComponent(location.hash.slice(1)),
    observer: null,
    previewTimer: null,
    hidePreviewTimer: null,
    previewController: null,
    toastTimer: null,
  };

  const els = {
    fileTree: document.querySelector("#fileTree"),
    fileSearch: document.querySelector("#fileSearch"),
    fileCount: document.querySelector("#fileCount"),
    content: document.querySelector("#documentContent"),
    status: document.querySelector("#documentStatus"),
    footer: document.querySelector("#documentFooter"),
    toc: document.querySelector("#tableOfContents"),
    breadcrumbs: document.querySelector("#breadcrumbs"),
    preview: document.querySelector("#linkPreview"),
    previewPath: document.querySelector("#previewPath"),
    previewContent: document.querySelector("#previewContent"),
    readingMeta: document.querySelector("#readingMeta"),
    progress: document.querySelector("#readingProgress"),
    lightbox: document.querySelector("#lightbox"),
    toast: document.querySelector("#toast"),
  };

  const icons = {
    folder: '<svg viewBox="0 0 24 24"><path d="M3 6.8a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8.4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/></svg>',
    markdown: '<svg viewBox="0 0 24 24"><path d="M6 3.5h8l4 4v13H6a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2Z"/><path d="M14 3.5v4h4M7 16v-5l2 2 2-2v5M13 14l2 2 2-2M15 11v5"/></svg>',
    file: '<svg viewBox="0 0 24 24"><path d="M6 3.5h8l4 4v13H6a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2Z"/><path d="M14 3.5v4h4"/></svg>',
  };

  async function getJSON(url, options = {}) {
    const response = await fetch(url, options);
    if (!response.ok) throw new Error(`Request failed: ${response.status}`);
    return response.json();
  }

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = String(value);
    return div.innerHTML;
  }

  function createTree(nodes, filter = "") {
    const fragment = document.createDocumentFragment();
    const query = filter.trim().toLocaleLowerCase();
    let visibleCount = 0;

    for (const node of nodes) {
      if (node.type === "folder") {
        const childResult = createTree(node.children, filter);
        const selfMatches = node.name.toLocaleLowerCase().includes(query);
        if (query && !selfMatches && childResult.visibleCount === 0) continue;

        const group = document.createElement("div");
        group.className = "tree-group";
        group.dataset.path = node.path;
        const row = document.createElement("div");
        row.className = "tree-row";
        row.style.paddingLeft = "6px";
        row.innerHTML = `<span class="tree-toggle">⌄</span><span class="tree-icon">${icons.folder}</span><span class="tree-label">${escapeHtml(node.name)}</span>`;
        row.title = node.path;
        row.addEventListener("click", () => group.classList.toggle("collapsed"));
        const children = document.createElement("div");
        children.className = "tree-children";
        children.append(childResult.fragment);
        group.append(row, children);
        fragment.append(group);
        visibleCount += childResult.visibleCount;
      } else {
        if (query && !node.name.toLocaleLowerCase().includes(query) && !node.path.toLocaleLowerCase().includes(query)) continue;
        const row = document.createElement("a");
        row.className = `tree-row tree-file${node.path === state.currentPath ? " active" : ""}`;
        row.dataset.path = node.path;
        row.title = node.path;
        row.href = node.type === "markdown" ? `/?file=${encodeURIComponent(node.path)}` : `/api/raw?path=${encodeURIComponent(node.path)}`;
        if (node.type !== "markdown") row.target = "_blank";
        row.innerHTML = `<span class="tree-toggle"></span><span class="tree-icon">${node.type === "markdown" ? icons.markdown : icons.file}</span><span class="tree-label">${escapeHtml(node.name)}</span>`;
        if (node.type === "markdown") {
          row.addEventListener("click", (event) => {
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            navigate(node.path);
          });
        }
        fragment.append(row);
        visibleCount += 1;
      }
    }
    return { fragment, visibleCount };
  }

  function renderTree(filter = "") {
    const { fragment, visibleCount } = createTree(state.project.tree, filter);
    els.fileTree.replaceChildren(fragment);
    if (visibleCount === 0) {
      const empty = document.createElement("div");
      empty.className = "tree-empty";
      empty.textContent = "没有匹配的文件";
      els.fileTree.append(empty);
    }
    expandCurrentTreePath();
  }

  function expandCurrentTreePath() {
    const active = els.fileTree.querySelector(`[data-path="${CSS.escape(state.currentPath)}"]`);
    if (!active) return;
    active.classList.add("active");
    let parent = active.parentElement;
    while (parent && parent !== els.fileTree) {
      if (parent.classList.contains("tree-group")) parent.classList.remove("collapsed");
      parent = parent.parentElement;
    }
    active.scrollIntoView({ block: "nearest" });
  }

  function renderBreadcrumbs(path) {
    const parts = path.split("/");
    const nodes = [state.project.name, ...parts];
    els.breadcrumbs.innerHTML = nodes.map((part, index) => {
      const separator = index ? '<span class="breadcrumb-chevron">/</span>' : "";
      return `${separator}<span class="breadcrumb-part" title="${escapeHtml(part)}">${escapeHtml(part)}</span>`;
    }).join("");
  }

  function renderToc(items) {
    els.toc.replaceChildren();
    if (!items.length) {
      els.toc.innerHTML = '<span class="tree-empty">本文没有标题</span>';
      return;
    }
    const minLevel = Math.min(...items.map((item) => item.level));
    for (const item of items) {
      const link = document.createElement("a");
      link.className = "toc-link";
      link.href = `#${encodeURIComponent(item.id)}`;
      link.dataset.headingId = item.id;
      link.style.setProperty("--indent", `${Math.min(item.level - minLevel, 3) * 12}px`);
      link.textContent = item.title;
      link.addEventListener("click", (event) => {
        event.preventDefault();
        scrollToAnchor(item.id, true);
      });
      els.toc.append(link);
    }
    observeHeadings(items);
  }

  function observeHeadings(items) {
    state.observer?.disconnect();
    const headings = items.map((item) => document.getElementById(item.id)).filter(Boolean);
    state.observer = new IntersectionObserver((entries) => {
      const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      let id = visible[0]?.target.id;
      if (!id) {
        const above = headings.filter((heading) => heading.getBoundingClientRect().top < 100);
        id = above.at(-1)?.id || headings[0]?.id;
      }
      if (!id) return;
      els.toc.querySelectorAll(".toc-link").forEach((link) => link.classList.toggle("active", link.dataset.headingId === id));
      els.toc.querySelector(".toc-link.active")?.scrollIntoView({ block: "nearest" });
    }, { rootMargin: "-76px 0px -68% 0px", threshold: [0, 1] });
    headings.forEach((heading) => state.observer.observe(heading));
  }

  function scrollToAnchor(anchor, updateHistory = false) {
    if (!anchor) {
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    let target = document.getElementById(anchor);
    if (!target) {
      const decoded = decodeURIComponent(anchor).toLocaleLowerCase();
      target = [...els.content.querySelectorAll("h1,h2,h3,h4,h5,h6")].find((heading) => heading.textContent.trim().toLocaleLowerCase() === decoded);
    }
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
      if (updateHistory) history.replaceState({ path: state.currentPath }, "", `/?file=${encodeURIComponent(state.currentPath)}#${encodeURIComponent(target.id)}`);
    }
  }

  async function enhanceDocument() {
    els.content.querySelectorAll(".copy-code").forEach((button) => {
      button.addEventListener("click", async () => {
        const code = button.closest(".code-block")?.querySelector("code")?.textContent || "";
        try {
          await navigator.clipboard.writeText(code);
          button.textContent = "Copied";
          setTimeout(() => { button.textContent = "Copy"; }, 1400);
        } catch {
          showToast("无法访问剪贴板");
        }
      });
    });

    els.content.querySelectorAll("img").forEach((image) => {
      image.addEventListener("click", () => openLightbox(image));
    });

    if (window.mermaid) {
      try {
        window.mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: "base",
          themeVariables: {
            primaryColor: "#eaf0ff",
            primaryTextColor: "#1f2329",
            primaryBorderColor: "#7aa2ff",
            lineColor: "#697386",
            secondaryColor: "#f4f6f8",
            tertiaryColor: "#ffffff",
            fontFamily: "Inter, PingFang SC, Microsoft YaHei, sans-serif",
          },
          flowchart: { htmlLabels: true, curve: "basis" },
        });
        const diagrams = [...els.content.querySelectorAll("pre.mermaid")];
        if (diagrams.length) {
          await window.mermaid.run({ nodes: diagrams, suppressErrors: true });
          diagrams.forEach((diagram) => { diagram.closest(".diagram-shell").dataset.diagramState = "ready"; });
        }
      } catch (error) {
        console.warn("Mermaid rendering failed", error);
        els.content.querySelectorAll(".diagram-shell[data-diagram-state='pending']").forEach((shell) => { shell.dataset.diagramState = "error"; });
      }
    }

    if (window.MathJax?.typesetPromise) {
      try { await window.MathJax.typesetPromise([els.content]); } catch (error) { console.warn("Math rendering failed", error); }
    }
  }

  async function navigate(path, anchor = "", options = {}) {
    hidePreview(true);
    state.currentPath = path;
    state.currentAnchor = anchor;
    els.status.hidden = false;
    els.status.classList.remove("error");
    els.status.innerHTML = '<span class="loading-spinner"></span><span>正在打开文档…</span>';
    els.content.innerHTML = "";
    els.footer.hidden = true;
    state.observer?.disconnect();

    try {
      const data = await getJSON(`/api/document?path=${encodeURIComponent(path)}`);
      state.currentPath = data.path;
      els.content.innerHTML = data.html;
      els.status.hidden = true;
      els.footer.hidden = false;
      els.readingMeta.textContent = `${data.stats.minutes} 分钟阅读 · ${data.modified}`;
      document.title = `${data.title} · ${state.project.name}`;
      renderBreadcrumbs(data.path);
      renderToc(data.toc);
      renderTree(els.fileSearch.value);
      await enhanceDocument();

      if (!options.popstate) {
        const suffix = anchor ? `#${encodeURIComponent(anchor)}` : "";
        history.pushState({ path: data.path, anchor }, "", `/?file=${encodeURIComponent(data.path)}${suffix}`);
      }
      if (anchor) requestAnimationFrame(() => scrollToAnchor(anchor));
      else window.scrollTo({ top: 0, behavior: options.instant ? "auto" : "smooth" });
      document.body.classList.remove("left-open");
      updateProgress();
    } catch (error) {
      els.status.hidden = false;
      els.status.classList.add("error");
      els.status.innerHTML = "<span>无法打开这个 Markdown 文件。请确认文件仍位于项目目录中。</span>";
      console.error(error);
    }
  }

  function setupDocumentLinks() {
    els.content.addEventListener("click", (event) => {
      const link = event.target.closest("a");
      if (!link) return;
      if (link.classList.contains("cross-document-link") && !(event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)) {
        event.preventDefault();
        navigate(link.dataset.docPath, link.dataset.anchor || "");
      } else if (link.classList.contains("anchor-link")) {
        event.preventDefault();
        scrollToAnchor(link.dataset.anchor || link.hash.slice(1), true);
      }
    });

    els.content.addEventListener("pointerover", (event) => {
      if (event.pointerType === "touch") return;
      const link = event.target.closest("a.document-link");
      if (!link || link.contains(event.relatedTarget)) return;
      clearTimeout(state.hidePreviewTimer);
      clearTimeout(state.previewTimer);
      state.previewTimer = setTimeout(() => showPreview(link), 360);
    });

    els.content.addEventListener("pointerout", (event) => {
      const link = event.target.closest("a.document-link");
      if (!link || link.contains(event.relatedTarget)) return;
      clearTimeout(state.previewTimer);
      state.hidePreviewTimer = setTimeout(() => hidePreview(), 220);
    });
    els.preview.addEventListener("pointerenter", () => clearTimeout(state.hidePreviewTimer));
    els.preview.addEventListener("pointerleave", () => { state.hidePreviewTimer = setTimeout(() => hidePreview(), 160); });
  }

  async function showPreview(link) {
    const path = link.dataset.docPath || state.currentPath;
    const anchor = link.dataset.anchor || "";
    state.previewController?.abort();
    state.previewController = new AbortController();
    els.previewPath.textContent = path;
    els.previewContent.innerHTML = '<div class="document-status"><span class="loading-spinner"></span></div>';
    els.preview.hidden = false;
    positionPreview(link);
    try {
      const data = await getJSON(`/api/preview?path=${encodeURIComponent(path)}&anchor=${encodeURIComponent(anchor)}`, { signal: state.previewController.signal });
      els.previewPath.textContent = data.path;
      els.previewContent.innerHTML = data.html;
      positionPreview(link);
    } catch (error) {
      if (error.name !== "AbortError") hidePreview(true);
    }
  }

  function positionPreview(link) {
    const rect = link.getBoundingClientRect();
    const width = Math.min(430, window.innerWidth - 24);
    const previewHeight = Math.min(480, els.preview.scrollHeight || 260);
    let left = rect.left + Math.min(rect.width, 30);
    left = Math.max(12, Math.min(left, window.innerWidth - width - 12));
    let top = rect.bottom + 9;
    if (top + previewHeight > window.innerHeight - 12) top = Math.max(12, rect.top - previewHeight - 9);
    els.preview.style.left = `${left}px`;
    els.preview.style.top = `${top}px`;
  }

  function hidePreview(immediate = false) {
    clearTimeout(state.previewTimer);
    clearTimeout(state.hidePreviewTimer);
    if (immediate) state.previewController?.abort();
    els.preview.hidden = true;
  }

  function openLightbox(source) {
    const image = els.lightbox.querySelector("img");
    image.src = source.currentSrc || source.src;
    image.alt = source.alt || "图片预览";
    els.lightbox.hidden = false;
    document.body.style.overflow = "hidden";
  }

  function closeLightbox() {
    els.lightbox.hidden = true;
    els.lightbox.querySelector("img").removeAttribute("src");
    document.body.style.overflow = "";
  }

  function showToast(message) {
    clearTimeout(state.toastTimer);
    els.toast.textContent = message;
    els.toast.hidden = false;
    state.toastTimer = setTimeout(() => { els.toast.hidden = true; }, 1800);
  }

  function updateProgress() {
    const documentTop = els.content.offsetTop;
    const total = Math.max(1, els.content.offsetHeight - window.innerHeight + 100);
    const progress = Math.max(0, Math.min(1, (window.scrollY - documentTop + 90) / total));
    els.progress.style.width = `${progress * 100}%`;
  }

  function bindUI() {
    els.fileSearch.addEventListener("input", () => renderTree(els.fileSearch.value));
    document.querySelector("#refreshDocument").addEventListener("click", () => navigate(state.currentPath, state.currentAnchor, { popstate: true, instant: true }));
    document.querySelector("#toggleRight").addEventListener("click", () => document.body.classList.toggle("right-collapsed"));
    document.querySelector("#openLeft").addEventListener("click", () => document.body.classList.add("left-open"));
    document.querySelector("#closeLeft").addEventListener("click", () => document.body.classList.remove("left-open"));
    document.querySelector("#mobileScrim").addEventListener("click", () => document.body.classList.remove("left-open"));
    document.querySelector("#backToTop").addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
    els.lightbox.addEventListener("click", (event) => { if (event.target === els.lightbox || event.target.closest(".lightbox-close")) closeLightbox(); });
    window.addEventListener("scroll", updateProgress, { passive: true });
    window.addEventListener("resize", () => hidePreview(true), { passive: true });
    window.addEventListener("popstate", () => {
      const params = new URLSearchParams(location.search);
      navigate(params.get("file") || state.project.initialFile, decodeURIComponent(location.hash.slice(1)), { popstate: true, instant: true });
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        hidePreview(true);
        if (!els.lightbox.hidden) closeLightbox();
        document.body.classList.remove("left-open");
      }
      if (event.key === "/" && !event.ctrlKey && !event.metaKey && !/INPUT|TEXTAREA/.test(document.activeElement.tagName)) {
        event.preventDefault();
        els.fileSearch.focus();
      }
    });
  }

  async function init() {
    bindUI();
    setupDocumentLinks();
    try {
      state.project = await getJSON("/api/project");
      const countFiles = (nodes) => nodes.reduce((sum, node) => sum + (node.type === "folder" ? countFiles(node.children) : 1), 0);
      els.fileCount.textContent = `${countFiles(state.project.tree)} files`;
      renderTree();
      history.replaceState({ path: state.currentPath, anchor: state.currentAnchor }, "", location.href);
      await navigate(state.currentPath, state.currentAnchor, { popstate: true, instant: true });
    } catch (error) {
      els.status.classList.add("error");
      els.status.innerHTML = "<span>阅读器初始化失败。请检查终端中的错误信息。</span>";
      console.error(error);
    }
  }

  init();
})();
