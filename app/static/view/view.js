const language = localStorage.getItem("docugenLanguage") === "ko" ? "ko" : "en";

const copy = {
  en: {
    appTitle: "LLM Document Agent",
    backToEditor: "Back to editor",
    documentView: "Document View",
    draftVersion: "Draft v{version}",
    emptyBody: "Run the writing pipeline to generate a draft for this project.",
    emptyTitle: "No draft yet",
    errorTitle: "Could not load document",
    loading: "Loading draft…",
    missingProject: "Add ?project={id} to the URL to open a project draft.",
    noDraft: "This project does not have a draft artifact yet.",
    print: "Print",
    seoDefaultDescription: "Read project drafts in an A4 document layout.",
    updated: "Updated",
  },
  ko: {
    appTitle: "LLM 문서 작성 에이전트",
    backToEditor: "편집기로 돌아가기",
    documentView: "양식 보기",
    draftVersion: "초안 v{version}",
    emptyBody: "이 프로젝트의 초안을 만들려면 작성 파이프라인을 실행하세요.",
    emptyTitle: "초안 없음",
    errorTitle: "문서를 불러올 수 없습니다",
    loading: "초안 불러오는 중…",
    missingProject: "URL에 ?project={id} 를 지정해 프로젝트 초안을 여세요.",
    noDraft: "이 프로젝트에는 아직 초안 산출물이 없습니다.",
    print: "인쇄",
    seoDefaultDescription: "프로젝트 초안을 A4 양식으로 확인합니다.",
    updated: "수정",
  },
};

function t(key, params = {}) {
  const template = copy[language]?.[key] || copy.en[key] || key;
  return Object.entries(params).reduce(
    (text, [name, value]) => text.replaceAll(`{${name}}`, String(value)),
    template,
  );
}

const els = {
  toolbarEyebrow: document.querySelector("#toolbarEyebrow"),
  toolbarTitle: document.querySelector("#toolbarTitle"),
  toolbarMeta: document.querySelector("#toolbarMeta"),
  backLink: document.querySelector("#backLink"),
  printButton: document.querySelector("#printButton"),
  viewStage: document.querySelector("#viewStage"),
  docTitle: document.querySelector("#docTitle"),
  docMeta: document.querySelector("#docMeta"),
  docModified: document.querySelector("#docModified"),
  docBody: document.querySelector("#docBody"),
  viewEmpty: document.querySelector("#viewEmpty"),
  emptyTitle: document.querySelector("#emptyTitle"),
  emptyBody: document.querySelector("#emptyBody"),
  viewError: document.querySelector("#viewError"),
  errorTitle: document.querySelector("#errorTitle"),
  errorBody: document.querySelector("#errorBody"),
};

function projectIdFromUrl() {
  return new URLSearchParams(window.location.search).get("project")?.trim() || null;
}

function canonicalViewUrl(projectId) {
  const url = new URL(window.location.origin);
  url.pathname = "/view";
  url.search = projectId ? `?project=${encodeURIComponent(projectId)}` : "";
  return url.toString();
}

function editorUrl(projectId) {
  return projectId ? `/ui/?project=${encodeURIComponent(projectId)}` : "/ui/";
}

function stripMarkdown(text) {
  return String(text || "")
    .replace(/\r\n/g, "\n")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]+\)/g, " ")
    .replace(/\[\[\d+\]\]\([^)]+\)/g, " ")
    .replace(/\[\([^()\n]{1,120}\)\]\([^)]+\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^>\s?/gm, "")
    .replace(/^[-*]\s+/gm, "")
    .replace(/^\d+\.\s+/gm, "")
    .replace(/\|/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function buildDescription(project, markdown) {
  const source = stripMarkdown(markdown || project.initial_request || "");
  const title = String(project.title || "").trim();
  let excerpt = source;
  if (source && !source.toLowerCase().startsWith(title.toLowerCase())) {
    excerpt = title ? `${title} — ${source}` : source;
  } else if (!excerpt) {
    excerpt = title;
  }
  if (excerpt.length <= 160) return excerpt;
  const cut = excerpt.slice(0, 159).trimEnd();
  const lastSpace = cut.lastIndexOf(" ");
  return `${lastSpace > 0 ? cut.slice(0, lastSpace) : cut}…`;
}

function setMetaTag(name, content, { property = false } = {}) {
  const selector = property ? `meta[property="${name}"]` : `meta[name="${name}"]`;
  let node = document.head.querySelector(selector);
  if (!content) {
    node?.remove();
    return;
  }
  if (!node) {
    node = document.createElement("meta");
    if (property) node.setAttribute("property", name);
    else node.setAttribute("name", name);
    document.head.appendChild(node);
  }
  node.setAttribute("content", content);
}

function setLinkTag(rel, href) {
  let node = document.head.querySelector(`link[rel="${rel}"]`);
  if (!href) {
    node?.remove();
    return;
  }
  if (!node) {
    node = document.createElement("link");
    node.setAttribute("rel", rel);
    document.head.appendChild(node);
  }
  node.setAttribute("href", href);
}

function setJsonLd(data) {
  let node = document.head.querySelector('script[type="application/ld+json"][data-seo="document"]');
  if (!data) {
    node?.remove();
    return;
  }
  if (!node) {
    node = document.createElement("script");
    node.type = "application/ld+json";
    node.dataset.seo = "document";
    document.head.appendChild(node);
  }
  node.textContent = JSON.stringify(data);
}

function applySeo({
  title,
  description,
  pageUrl,
  robots,
  modified,
  published,
  version,
}) {
  document.title = title;
  setMetaTag("description", description);
  setMetaTag("robots", robots);
  setLinkTag("canonical", pageUrl);
  setMetaTag("og:type", "article", { property: true });
  setMetaTag("og:site_name", t("appTitle"), { property: true });
  setMetaTag("og:title", title, { property: true });
  setMetaTag("og:description", description, { property: true });
  setMetaTag("og:url", pageUrl, { property: true });
  setMetaTag("og:locale", language === "ko" ? "ko_KR" : "en_US", { property: true });
  setMetaTag("twitter:card", "summary");
  setMetaTag("twitter:title", title);
  setMetaTag("twitter:description", description);

  if (robots.includes("index")) {
    setJsonLd({
      "@context": "https://schema.org",
      "@type": "Article",
      headline: title.split(" · ")[0] || title,
      description,
      url: pageUrl,
      datePublished: published,
      dateModified: modified,
      version: version ? String(version) : undefined,
      isPartOf: {
        "@type": "WebSite",
        name: t("appTitle"),
        url: `${window.location.origin}/ui/`,
      },
      publisher: {
        "@type": "Organization",
        name: t("appTitle"),
      },
    });
  } else {
    setJsonLd(null);
  }
}

async function api(path) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
  });
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json")
    ? await response.json()
    : await response.text();
  if (!response.ok) {
    const detail = typeof body === "object" && body.detail ? body.detail : response.statusText;
    throw new Error(detail);
  }
  return body;
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(language === "ko" ? "ko-KR" : "en-US");
}

function latestDraft(artifacts) {
  return artifacts.find((artifact) => artifact.type === "draft") || null;
}

function showError(message) {
  els.viewStage.classList.add("hidden");
  els.viewEmpty.classList.add("hidden");
  els.viewError.classList.remove("hidden");
  els.errorTitle.textContent = t("errorTitle");
  els.errorBody.textContent = message;
}

function showEmpty(message) {
  els.viewStage.classList.add("hidden");
  els.viewError.classList.add("hidden");
  els.viewEmpty.classList.remove("hidden");
  els.emptyTitle.textContent = t("emptyTitle");
  els.emptyBody.textContent = message;
}

async function renderMermaid() {
  if (!window.mermaid) return;
  const nodes = [...els.docBody.querySelectorAll(".mermaid")];
  if (!nodes.length) return;
  window.mermaid.initialize({ startOnLoad: false, securityLevel: "loose" });
  let index = 0;
  for (const node of nodes) {
    const source = node.textContent || "";
    const id = `mermaid-view-${index}`;
    index += 1;
    try {
      const { svg } = await window.mermaid.render(id, source);
      node.innerHTML = svg;
    } catch {
      node.textContent = source;
    }
  }
}

function applyStaticCopy() {
  document.documentElement.lang = language;
  els.toolbarEyebrow.textContent = t("appTitle");
  els.toolbarTitle.textContent = t("documentView");
  els.backLink.textContent = t("backToEditor");
  els.printButton.textContent = t("print");
}

function setDocMeta(version, updatedAt) {
  const versionLabel = t("draftVersion", { version });
  const updatedLabel = `${t("updated")} ${formatDate(updatedAt)}`;
  if (els.docModified) {
    els.docModified.dateTime = updatedAt || "";
    els.docModified.textContent = `${versionLabel} · ${updatedLabel}`;
  } else {
    els.docMeta.textContent = `${versionLabel} · ${updatedLabel}`;
  }
}

async function boot() {
  applyStaticCopy();
  els.toolbarMeta.textContent = t("loading");

  const projectId = projectIdFromUrl();
  els.backLink.href = editorUrl(projectId);

  if (!projectId) {
    applySeo({
      title: t("documentView"),
      description: t("seoDefaultDescription"),
      pageUrl: canonicalViewUrl(null),
      robots: "noindex, nofollow",
    });
    showError(t("missingProject"));
    els.toolbarMeta.textContent = "";
    return;
  }

  try {
    const [project, artifacts] = await Promise.all([
      api(`/projects/${projectId}`),
      api(`/projects/${projectId}/artifacts`),
    ]);
    const draft = latestDraft(artifacts);
    const pageUrl = canonicalViewUrl(project.id);
    const description = buildDescription(
      project,
      draft?.content?.markdown || "",
    );
    const documentTitle = `${project.title} · ${t("documentView")}`;

    els.backLink.href = editorUrl(project.id);
    els.toolbarMeta.textContent = project.title;

    if (!draft?.content?.markdown) {
      applySeo({
        title: documentTitle,
        description,
        pageUrl,
        robots: "noindex, nofollow",
        modified: project.updated_at,
        published: project.created_at,
      });
      showEmpty(t("noDraft"));
      return;
    }

    applySeo({
      title: documentTitle,
      description,
      pageUrl,
      robots: "index, follow",
      modified: draft.updated_at,
      published: project.created_at,
      version: draft.version,
    });

    const rendered = DocuGenMarkdown.renderMarkdown(draft.content.markdown, {
      emptyMessage: t("noDraft"),
    });
    els.docTitle.textContent = project.title;
    setDocMeta(draft.version, draft.updated_at);
    els.docBody.innerHTML = rendered.html;

    els.viewEmpty.classList.add("hidden");
    els.viewError.classList.add("hidden");
    els.viewStage.classList.remove("hidden");

    await renderMermaid();
  } catch (error) {
    applySeo({
      title: t("documentView"),
      description: t("seoDefaultDescription"),
      pageUrl: canonicalViewUrl(projectId),
      robots: "noindex, nofollow",
    });
    els.toolbarMeta.textContent = "";
    showError(error.message);
  }
}

els.printButton.addEventListener("click", () => window.print());

boot();
