(() => {
  "use strict";

  const state = {
    project: null,
    recentWorkspaces: [],
    directoryBrowser: null,
    workspaceToken: document.body.dataset.workspaceToken,
    currentPath: document.body.dataset.initialFile,
    currentAnchor: decodeURIComponent(location.hash.slice(1)),
    observer: null,
    previewTimer: null,
    hidePreviewTimer: null,
    previewController: null,
    toastTimer: null,
    mode: "read",
    editorOriginal: "",
    editorVersion: "",
    editorWorkspace: "",
    editorDirty: false,
    editorSaving: false,
    collapsedSections: new Map(),
    sectionAncestors: new WeakMap(),
    foldHeadings: [],
    collapsedListItems: new Map(),
    foldListItems: [],
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
    workspaceName: document.querySelector("#workspaceName"),
    workspaceBackdrop: document.querySelector("#workspaceBackdrop"),
    workspaceForm: document.querySelector("#workspaceForm"),
    workspacePath: document.querySelector("#workspacePath"),
    workspaceList: document.querySelector("#workspaceList"),
    workspaceError: document.querySelector("#workspaceError"),
    switchWorkspace: document.querySelector("#switchWorkspace"),
    welcome: document.querySelector("#workspaceWelcome"),
    directoryBrowser: document.querySelector("#directoryBrowser"),
    directoryLocation: document.querySelector("#directoryLocation"),
    directoryList: document.querySelector("#directoryList"),
    directoryUp: document.querySelector("#directoryUp"),
    directoryStatus: document.querySelector("#directoryStatus"),
    chooseCurrentDirectory: document.querySelector("#chooseCurrentDirectory"),
    readMode: document.querySelector("#readMode"),
    editMode: document.querySelector("#editMode"),
    cancelEdit: document.querySelector("#cancelEdit"),
    saveDocument: document.querySelector("#saveDocument"),
    editor: document.querySelector("#editorShell"),
    editorPath: document.querySelector("#editorPath"),
    editorState: document.querySelector("#editorState"),
    sourceEditor: document.querySelector("#sourceEditor"),
    toggleAllSections: document.querySelector("#toggleAllSections"),
  };

  const icons = {
    folder: '<svg viewBox="0 0 24 24"><path d="M3 6.8a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8.4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/></svg>',
    markdown: '<svg viewBox="0 0 24 24"><path d="M6 3.5h8l4 4v13H6a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2Z"/><path d="M14 3.5v4h4M7 16v-5l2 2 2-2v5M13 14l2 2 2-2M15 11v5"/></svg>',
    file: '<svg viewBox="0 0 24 24"><path d="M6 3.5h8l4 4v13H6a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2Z"/><path d="M14 3.5v4h4"/></svg>',
  };

  async function getJSON(url, options = {}) {
    const response = await fetch(url, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(payload.error || `Request failed: ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function updateProjectChrome() {
    const countFiles = (nodes) => nodes.reduce((sum, node) => sum + (node.type === "folder" ? countFiles(node.children) : 1), 0);
    els.workspaceName.textContent = state.project.name;
    els.workspaceName.title = state.project.root;
    els.fileCount.textContent = `${countFiles(state.project.tree)} files`;
    document.body.dataset.projectName = state.project.name;
    els.welcome.hidden = state.project.initialized;
    els.status.hidden = !state.project.initialized;
    els.editMode.disabled = !state.project.initialized;
  }

  function setEditorDirty(dirty) {
    state.editorDirty = dirty;
    els.editorState.textContent = dirty ? "有未保存更改" : "未修改";
    els.editorState.classList.toggle("dirty", dirty);
    els.saveDocument.disabled = !dirty || state.editorSaving;
  }

  function setMode(mode) {
    state.mode = mode;
    const editing = mode === "edit";
    document.body.classList.toggle("editing", editing);
    els.readMode.classList.toggle("active", !editing);
    els.readMode.setAttribute("aria-pressed", String(!editing));
    els.editMode.classList.toggle("active", editing);
    els.editMode.setAttribute("aria-pressed", String(editing));
    els.cancelEdit.hidden = !editing;
    els.saveDocument.hidden = !editing;
    els.editor.hidden = !editing;
    els.content.hidden = editing;
    els.footer.hidden = editing || !state.currentPath;
    els.readingMeta.hidden = editing;
    if (!editing) {
      els.sourceEditor.value = "";
      state.editorOriginal = "";
      state.editorVersion = "";
      state.editorWorkspace = "";
      setEditorDirty(false);
    }
  }

  function confirmEditorLeave() {
    return !state.editorDirty || window.confirm("当前文档有未保存的更改，确定要放弃吗？");
  }

  async function enterEditMode() {
    if (state.mode === "edit" || !state.project?.initialized || !state.currentPath) return;
    const requestedPath = state.currentPath;
    const requestedWorkspace = state.project.root;
    els.editMode.disabled = true;
    els.editMode.textContent = "载入中…";
    try {
      const data = await getJSON(`/api/source?path=${encodeURIComponent(requestedPath)}`, {
        headers: { "X-Workspace-Token": state.workspaceToken },
      });
      if (state.currentPath !== requestedPath || state.project.root !== requestedWorkspace) return;
      state.editorOriginal = data.source;
      state.editorVersion = data.version;
      state.editorWorkspace = data.workspace;
      els.sourceEditor.value = data.source;
      els.editorPath.textContent = data.path;
      els.editorPath.title = data.path;
      setMode("edit");
      setEditorDirty(false);
      requestAnimationFrame(() => els.sourceEditor.focus());
    } catch (error) {
      showToast(error.message || "无法打开编辑模式");
    } finally {
      els.editMode.disabled = !state.project?.initialized;
      els.editMode.textContent = "编辑";
    }
  }

  function cancelEditing() {
    if (state.mode !== "edit") return true;
    if (!confirmEditorLeave()) return false;
    setMode("read");
    return true;
  }

  async function saveDocument() {
    if (state.mode !== "edit" || !state.editorDirty || state.editorSaving) return;
    state.editorSaving = true;
    els.saveDocument.disabled = true;
    els.saveDocument.textContent = "保存中…";
    els.editorState.textContent = "正在保存";
    try {
      const data = await getJSON("/api/source", {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "X-Workspace-Token": state.workspaceToken,
        },
        body: JSON.stringify({
          path: state.currentPath,
          source: els.sourceEditor.value,
          version: state.editorVersion,
          workspace: state.editorWorkspace,
        }),
      });
      state.editorOriginal = data.source;
      state.editorVersion = data.version;
      setEditorDirty(false);
      setMode("read");
      await navigate(state.currentPath, "", { popstate: true, instant: true, skipEditorGuard: true });
      showToast("文档已保存");
    } catch (error) {
      els.editorState.textContent = error.status === 409 ? "保存冲突" : "保存失败";
      els.editorState.classList.add("dirty");
      showToast(error.message || "保存失败");
    } finally {
      state.editorSaving = false;
      els.saveDocument.textContent = "保存";
      if (state.mode === "edit") els.saveDocument.disabled = !state.editorDirty;
    }
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
    const parts = path ? path.split("/") : [];
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

  function currentSectionState() {
    const key = `${state.project?.root || ""}\u0000${state.currentPath || ""}`;
    if (!state.collapsedSections.has(key)) state.collapsedSections.set(key, new Set());
    return state.collapsedSections.get(key);
  }

  function currentListState() {
    const key = `${state.project?.root || ""}\u0000${state.currentPath || ""}`;
    if (!state.collapsedListItems.has(key)) state.collapsedListItems.set(key, new Set());
    return state.collapsedListItems.get(key);
  }

  function applySectionFolding() {
    const collapsed = currentSectionState();
    for (const element of els.content.children) {
      const owners = state.sectionAncestors.get(element) || [];
      element.classList.toggle("section-hidden", owners.some((id) => collapsed.has(id)));
    }

    for (const heading of state.foldHeadings) {
      const folded = collapsed.has(heading.id);
      heading.classList.toggle("section-collapsed", folded);
      const toggle = heading.querySelector(":scope > .section-toggle");
      if (toggle) {
        toggle.setAttribute("aria-expanded", String(!folded));
        const action = folded ? "展开" : "折叠";
        toggle.title = `${action}此章节`;
        toggle.setAttribute("aria-label", `${action}章节：${heading.dataset.sectionTitle}`);
      }
      const tocLink = els.toc.querySelector(`[data-heading-id="${CSS.escape(heading.id)}"]`);
      tocLink?.classList.toggle("section-collapsed", folded);
    }

    const allCollapsed = state.foldHeadings.length > 0 && state.foldHeadings.every((heading) => collapsed.has(heading.id));
    els.toggleAllSections.disabled = state.foldHeadings.length === 0;
    els.toggleAllSections.classList.toggle("all-collapsed", allCollapsed);
    els.toggleAllSections.title = allCollapsed ? "展开全部章节" : "折叠全部章节";
    els.toggleAllSections.setAttribute("aria-label", els.toggleAllSections.title);
    els.toggleAllSections.setAttribute("aria-pressed", String(allCollapsed));
    requestAnimationFrame(updateProgress);
  }

  function toggleSection(heading) {
    const collapsed = currentSectionState();
    if (collapsed.has(heading.id)) collapsed.delete(heading.id);
    else collapsed.add(heading.id);
    applySectionFolding();
  }

  function setupSectionFolding() {
    const collapsed = currentSectionState();
    const elements = [...els.content.children];
    const stack = [];
    const headings = [];
    state.sectionAncestors = new WeakMap();

    for (const element of elements) {
      if (element.matches("h1.document-heading,h2.document-heading,h3.document-heading,h4.document-heading,h5.document-heading,h6.document-heading")) {
        const level = Number(element.tagName.slice(1));
        while (stack.length && stack.at(-1).level >= level) stack.pop();
        state.sectionAncestors.set(element, stack.map((item) => item.heading.id));
        const title = element.textContent.trim();
        element.dataset.sectionTitle = title;
        element.setAttribute("aria-label", title);
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "section-toggle";
        toggle.setAttribute("aria-label", `折叠章节：${title}`);
        toggle.setAttribute("aria-expanded", "true");
        toggle.title = "折叠此章节";
        toggle.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4"/></svg>';
        toggle.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          toggleSection(element);
        });
        element.prepend(toggle);
        headings.push(element);
        stack.push({ level, heading: element });
      } else {
        state.sectionAncestors.set(element, stack.map((item) => item.heading.id));
      }
    }

    state.foldHeadings = headings;
    const availableIds = new Set(headings.map((heading) => heading.id));
    for (const id of [...collapsed]) {
      if (!availableIds.has(id)) collapsed.delete(id);
    }
    applySectionFolding();
  }

  function revealSectionFor(target) {
    let topLevel = target;
    while (topLevel?.parentElement && topLevel.parentElement !== els.content) topLevel = topLevel.parentElement;
    const owners = state.sectionAncestors.get(topLevel) || [];
    const collapsed = currentSectionState();
    let changed = false;
    for (const id of owners) changed = collapsed.delete(id) || changed;
    if (changed) applySectionFolding();
  }

  function toggleAllSections() {
    const collapsed = currentSectionState();
    const allCollapsed = state.foldHeadings.length > 0 && state.foldHeadings.every((heading) => collapsed.has(heading.id));
    if (allCollapsed) collapsed.clear();
    else state.foldHeadings.forEach((heading) => collapsed.add(heading.id));
    applySectionFolding();
  }

  function listItemSummary(item) {
    const parts = [];
    for (const node of item.childNodes) {
      if (node.nodeType === Node.TEXT_NODE) {
        parts.push(node.textContent);
        continue;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) continue;
      if (node.matches("ul,ol,blockquote,pre,table,figure,.code-block,.diagram-shell")) break;
      parts.push(node.textContent);
      if (node.matches("p")) break;
    }
    return parts.join(" ").replace(/\s+/g, " ").trim().slice(0, 100) || "未命名列表项";
  }

  function listItemSummaryParagraph(item) {
    const firstBlock = [...item.children].find((child) => child.matches("p,ul,ol,blockquote,pre,table,figure,.code-block,.diagram-shell,.math.block"));
    return firstBlock?.matches("p") ? firstBlock : null;
  }

  function foldableListChildren(item) {
    const children = [...item.children];
    const firstParagraph = listItemSummaryParagraph(item);
    return children.filter((child) => {
      if (child === firstParagraph) return false;
      return child.matches("ul,ol,p,blockquote,pre,table,figure,.code-block,.diagram-shell,.math.block");
    });
  }

  function applyListFolding() {
    const collapsed = currentListState();
    for (const entry of state.foldListItems) {
      const folded = collapsed.has(entry.id);
      entry.item.classList.toggle("list-item-collapsed", folded);
      entry.toggle.setAttribute("aria-expanded", String(!folded));
      const action = folded ? "展开" : "折叠";
      entry.toggle.title = `${action}此列表项`;
      entry.toggle.setAttribute("aria-label", `${action}列表项：${entry.title}`);
      entry.content.forEach((element) => element.classList.toggle("list-content-hidden", folded));
    }
    requestAnimationFrame(updateProgress);
  }

  function toggleListItem(entry) {
    const collapsed = currentListState();
    if (collapsed.has(entry.id)) collapsed.delete(entry.id);
    else collapsed.add(entry.id);
    applyListFolding();
  }

  function setupListFolding() {
    const collapsed = currentListState();
    const occurrences = new Map();
    const entries = [];

    for (const item of els.content.querySelectorAll("li")) {
      const content = foldableListChildren(item);
      if (!content.length) continue;
      const title = listItemSummary(item);
      const occurrence = occurrences.get(title) || 0;
      occurrences.set(title, occurrence + 1);
      const id = `${title}::${occurrence}`;
      const toggle = document.createElement("button");
      const entry = { item, toggle, content, id, title };
      toggle.type = "button";
      toggle.className = "list-toggle";
      toggle.setAttribute("aria-label", `折叠列表项：${title}`);
      toggle.setAttribute("aria-expanded", "true");
      toggle.title = "折叠此列表项";
      toggle.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4"/></svg>';
      toggle.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        toggleListItem(entry);
      });
      const firstParagraph = listItemSummaryParagraph(item);
      (firstParagraph || item).prepend(toggle);
      item.classList.add("foldable-list-item");
      content.forEach((element) => element.classList.add("list-fold-content"));
      entries.push(entry);
    }

    state.foldListItems = entries;
    const availableIds = new Set(entries.map((entry) => entry.id));
    for (const id of [...collapsed]) {
      if (!availableIds.has(id)) collapsed.delete(id);
    }
    applyListFolding();
  }

  function revealListFor(target) {
    const collapsed = currentListState();
    let item = target.closest?.("li.foldable-list-item");
    let changed = false;
    while (item) {
      const entry = state.foldListItems.find((candidate) => candidate.item === item);
      if (entry) changed = collapsed.delete(entry.id) || changed;
      item = item.parentElement?.closest("li.foldable-list-item");
    }
    if (changed) applyListFolding();
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
      revealSectionFor(target);
      revealListFor(target);
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
    if (state.mode === "edit" && !options.skipEditorGuard) {
      if (!confirmEditorLeave()) return false;
      setMode("read");
    }
    hidePreview(true);
    state.currentPath = path;
    state.currentAnchor = anchor;
    els.status.hidden = false;
    els.status.classList.remove("error");
    els.status.innerHTML = '<span class="loading-spinner"></span><span>正在打开文档…</span>';
    els.content.innerHTML = "";
    els.footer.hidden = true;
    state.observer?.disconnect();
    state.foldHeadings = [];
    state.sectionAncestors = new WeakMap();
    state.foldListItems = [];
    els.toggleAllSections.disabled = true;

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
      setupSectionFolding();
      setupListFolding();

      if (!options.popstate) {
        const suffix = anchor ? `#${encodeURIComponent(anchor)}` : "";
        history.pushState({ path: data.path, anchor }, "", `/?file=${encodeURIComponent(data.path)}${suffix}`);
      }
      if (anchor) requestAnimationFrame(() => scrollToAnchor(anchor));
      else window.scrollTo({ top: 0, behavior: options.instant ? "auto" : "smooth" });
      document.body.classList.remove("left-open");
      updateProgress();
      els.editMode.disabled = false;
      return true;
    } catch (error) {
      els.status.hidden = false;
      els.status.classList.add("error");
      els.status.innerHTML = "<span>无法打开这个 Markdown 文件。请确认文件仍位于项目目录中。</span>";
      console.error(error);
      els.editMode.disabled = !state.project?.initialized;
      return false;
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

  function renderWorkspaceList() {
    els.workspaceList.replaceChildren();
    if (!state.recentWorkspaces.length) {
      els.workspaceList.innerHTML = '<div class="tree-empty">还没有最近使用的工作区</div>';
      return;
    }
    for (const workspace of state.recentWorkspaces) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `workspace-item${workspace.current ? " current" : ""}`;
      button.disabled = !workspace.available || workspace.current;
      button.title = workspace.available ? workspace.path : "这个目录已不存在";
      button.innerHTML = `
        <span class="workspace-item-icon"><svg viewBox="0 0 24 24"><path d="M3 6.8a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8.4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/></svg></span>
        <span class="workspace-item-copy"><span class="workspace-item-name">${escapeHtml(workspace.name)}</span><span class="workspace-item-path">${escapeHtml(workspace.path)}</span></span>
        ${workspace.current ? '<span class="workspace-current-badge">当前</span>' : ""}`;
      if (workspace.available && !workspace.current) button.addEventListener("click", () => switchWorkspace(workspace.path));
      els.workspaceList.append(button);
    }
  }

  function renderDirectoryBrowser() {
    const data = state.directoryBrowser;
    els.directoryBrowser.hidden = !data;
    if (!data) return;
    els.directoryLocation.textContent = data.path;
    els.directoryLocation.title = data.path;
    els.directoryUp.disabled = !data.parent;
    els.directoryUp.dataset.path = data.parent || "";
    els.directoryStatus.textContent = data.hasMarkdown ? "当前目录包含 Markdown" : "选择后将检查子目录中的 Markdown";
    els.directoryStatus.classList.toggle("available", data.hasMarkdown);
    els.chooseCurrentDirectory.disabled = false;
    els.directoryList.replaceChildren();
    const entries = [...(data.drives || []), ...data.directories];
    if (!entries.length) {
      els.directoryList.innerHTML = '<div class="tree-empty">没有可浏览的子目录</div>';
      return;
    }
    for (const directory of entries) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "directory-entry";
      button.title = directory.path;
      button.innerHTML = `<svg viewBox="0 0 24 24"><path d="M3 6.8a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8.4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/></svg><span>${escapeHtml(directory.name)}</span>`;
      button.addEventListener("click", () => browseDirectory(directory.path));
      els.directoryList.append(button);
    }
  }

  async function browseDirectory(path = "") {
    els.workspaceError.hidden = true;
    try {
      const query = path ? `?path=${encodeURIComponent(path)}` : "";
      state.directoryBrowser = await getJSON(`/api/directories${query}`, {
        headers: { "X-Workspace-Token": state.workspaceToken },
      });
      renderDirectoryBrowser();
    } catch (error) {
      els.workspaceError.textContent = error.message;
      els.workspaceError.hidden = false;
    }
  }

  async function openWorkspaceSwitcher() {
    els.workspaceError.hidden = true;
    els.workspacePath.value = "";
    state.directoryBrowser = null;
    renderDirectoryBrowser();
    els.workspaceBackdrop.hidden = false;
    document.body.style.overflow = "hidden";
    try {
      const data = await getJSON("/api/workspaces");
      state.recentWorkspaces = data.recent;
      renderWorkspaceList();
    } catch (error) {
      els.workspaceError.textContent = error.message;
      els.workspaceError.hidden = false;
    }
    requestAnimationFrame(() => els.workspacePath.focus());
  }

  function closeWorkspaceSwitcher() {
    els.workspaceBackdrop.hidden = true;
    document.body.style.overflow = "";
  }

  async function switchWorkspace(path) {
    const candidate = path.trim();
    if (!candidate) {
      els.workspaceError.textContent = "请输入工作区目录。";
      els.workspaceError.hidden = false;
      return;
    }
    if (state.mode === "edit" && !confirmEditorLeave()) return;
    els.workspaceError.hidden = true;
    els.switchWorkspace.disabled = true;
    els.switchWorkspace.textContent = "打开中…";
    try {
      const data = await getJSON("/api/workspace", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Workspace-Token": state.workspaceToken,
        },
        body: JSON.stringify({ path: candidate }),
      });
      state.project = data.project;
      state.recentWorkspaces = data.recent;
      state.currentPath = state.project.initialFile;
      state.currentAnchor = "";
      setMode("read");
      els.fileSearch.value = "";
      updateProjectChrome();
      renderTree();
      closeWorkspaceSwitcher();
      await navigate(state.currentPath, "", { popstate: true, instant: true });
      history.replaceState({ path: state.currentPath, anchor: "" }, "", `/?file=${encodeURIComponent(state.currentPath)}`);
      showToast(`已切换到 ${state.project.name}`);
    } catch (error) {
      els.workspaceError.textContent = error.message;
      els.workspaceError.hidden = false;
    } finally {
      els.switchWorkspace.disabled = false;
      els.switchWorkspace.textContent = "打开";
    }
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
    els.readMode.addEventListener("click", cancelEditing);
    els.editMode.addEventListener("click", enterEditMode);
    els.cancelEdit.addEventListener("click", cancelEditing);
    els.saveDocument.addEventListener("click", saveDocument);
    els.toggleAllSections.addEventListener("click", toggleAllSections);
    els.sourceEditor.addEventListener("input", () => setEditorDirty(els.sourceEditor.value !== state.editorOriginal));
    els.sourceEditor.addEventListener("keydown", (event) => {
      if (event.key !== "Tab") return;
      event.preventDefault();
      const start = els.sourceEditor.selectionStart;
      const end = els.sourceEditor.selectionEnd;
      els.sourceEditor.setRangeText("  ", start, end, "end");
      setEditorDirty(els.sourceEditor.value !== state.editorOriginal);
    });
    document.querySelector("#toggleRight").addEventListener("click", () => document.body.classList.toggle("right-collapsed"));
    document.querySelector("#openLeft").addEventListener("click", () => document.body.classList.add("left-open"));
    document.querySelector("#closeLeft").addEventListener("click", () => document.body.classList.remove("left-open"));
    document.querySelector("#mobileScrim").addEventListener("click", () => document.body.classList.remove("left-open"));
    document.querySelector("#backToTop").addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
    document.querySelector("#openWorkspaceSwitcher").addEventListener("click", openWorkspaceSwitcher);
    document.querySelector("#welcomeChooseWorkspace").addEventListener("click", openWorkspaceSwitcher);
    document.querySelector("#closeWorkspaceSwitcher").addEventListener("click", closeWorkspaceSwitcher);
    document.querySelector("#browseWorkspace").addEventListener("click", () => browseDirectory(els.workspacePath.value.trim()));
    els.directoryUp.addEventListener("click", () => browseDirectory(els.directoryUp.dataset.path));
    els.chooseCurrentDirectory.addEventListener("click", () => switchWorkspace(state.directoryBrowser?.path || ""));
    els.workspaceForm.addEventListener("submit", (event) => { event.preventDefault(); switchWorkspace(els.workspacePath.value); });
    els.workspaceBackdrop.addEventListener("click", (event) => { if (event.target === els.workspaceBackdrop) closeWorkspaceSwitcher(); });
    els.lightbox.addEventListener("click", (event) => { if (event.target === els.lightbox || event.target.closest(".lightbox-close")) closeLightbox(); });
    window.addEventListener("scroll", updateProgress, { passive: true });
    window.addEventListener("resize", () => hidePreview(true), { passive: true });
    window.addEventListener("popstate", async () => {
      const params = new URLSearchParams(location.search);
      const path = params.get("file") || state.project.initialFile;
      if (path) {
        const moved = await navigate(path, decodeURIComponent(location.hash.slice(1)), { popstate: true, instant: true });
        if (!moved) {
          const hash = state.currentAnchor ? `#${encodeURIComponent(state.currentAnchor)}` : "";
          history.pushState({ path: state.currentPath, anchor: state.currentAnchor }, "", `/?file=${encodeURIComponent(state.currentPath)}${hash}`);
        }
      }
    });
    window.addEventListener("beforeunload", (event) => {
      if (!state.editorDirty) return;
      event.preventDefault();
      event.returnValue = "";
    });
    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === "s" && state.mode === "edit") {
        event.preventDefault();
        saveDocument();
        return;
      }
      if (event.key === "Escape") {
        hidePreview(true);
        if (!els.lightbox.hidden) {
          closeLightbox();
          return;
        }
        if (!els.workspaceBackdrop.hidden) {
          closeWorkspaceSwitcher();
          return;
        }
        document.body.classList.remove("left-open");
        if (state.mode === "edit") cancelEditing();
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
      updateProjectChrome();
      renderTree();
      history.replaceState({ path: state.currentPath, anchor: state.currentAnchor }, "", location.href);
      if (state.project.initialized) {
        state.currentPath = state.currentPath || state.project.initialFile;
        await navigate(state.currentPath, state.currentAnchor, { popstate: true, instant: true });
      } else {
        els.content.innerHTML = "";
        els.footer.hidden = true;
        els.toc.replaceChildren();
        renderBreadcrumbs("");
      }
    } catch (error) {
      els.status.classList.add("error");
      els.status.innerHTML = "<span>阅读器初始化失败。请检查终端中的错误信息。</span>";
      console.error(error);
    }
  }

  init();
})();
