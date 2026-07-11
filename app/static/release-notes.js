const releaseState = {
  language: localStorage.getItem("docugenLanguage") || "ko",
  theme: localStorage.getItem("docugenTheme") || "pastel",
  data: null,
};

const releaseCopy = {
  en: {
    pageTitle: "DocuGen · Features & Releases",
    subtitle: "Features & Releases",
    overview: "Overview",
    features: "Features",
    releases: "Release notes",
    theme: "Theme",
    language: "Language",
    back: "Back to workspace",
    footerBack: "Start writing",
    eyebrow: "Current release",
    heroTitle: "High-quality documents with a small language model",
    heroBody:
      "DocuGen gives a small model a focused job at each stage, then verifies structure, sources, evidence, continuity, and genre fit before the final document is assembled.",
    explore: "Explore the features",
    readRelease: "Read the release notes",
    workflowTitle: "From request to reviewed document",
    workflowBody: "A visible workflow keeps the user in control without exposing prompt engineering details.",
    featureTitle: "What DocuGen does",
    featureBody: "The core capabilities are designed around document quality, traceability, and efficient small-model context.",
    releaseTitle: "Release history",
    releaseBody: "Versioned changes, fixes, and limitations are recorded here.",
    loadError: "Release information could not be loaded.",
  },
  ko: {
    pageTitle: "DocuGen · 기능 및 릴리즈",
    subtitle: "기능 및 릴리즈",
    overview: "개요",
    features: "주요 기능",
    releases: "릴리즈 노트",
    theme: "테마",
    language: "언어",
    back: "작업 공간으로",
    footerBack: "문서 작성으로 돌아가기",
    eyebrow: "현재 릴리즈",
    heroTitle: "작은 언어 모델로 만드는 품질 높은 문서",
    heroBody:
      "DocuGen은 작은 모델이 단계마다 한 가지 작업에 집중하게 하고, 최종 문서를 조립하기 전에 구조·출처·근거·연속성·장르 적합성을 검증합니다.",
    explore: "주요 기능 살펴보기",
    readRelease: "릴리즈 노트 읽기",
    workflowTitle: "요청에서 검토된 문서까지",
    workflowBody: "프롬프트 기술을 노출하지 않으면서도 사용자가 전체 흐름을 확인하고 제어할 수 있습니다.",
    featureTitle: "DocuGen이 제공하는 기능",
    featureBody: "문서 품질, 추적 가능성, 소형 모델의 효율적인 문맥 사용을 중심으로 설계했습니다.",
    releaseTitle: "릴리즈 기록",
    releaseBody: "버전별 변경 사항, 수정 내용과 제한 사항을 기록합니다.",
    loadError: "릴리즈 정보를 불러오지 못했습니다.",
  },
};

function escapeReleaseHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function localized(value) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value[releaseState.language] || value.en || value.ko || "";
  }
  return value ?? "";
}

function renderList(items) {
  return `<ul>${(items || []).map((item) => `<li>${escapeReleaseHtml(item)}</li>`).join("")}</ul>`;
}

function renderReleasePage() {
  const copy = releaseCopy[releaseState.language];
  const data = releaseState.data;
  document.documentElement.lang = releaseState.language;
  document.title = copy.pageTitle;
  document.getElementById("brandSubtitle").textContent = copy.subtitle;
  document.getElementById("navOverview").textContent = copy.overview;
  document.getElementById("navFeatures").textContent = copy.features;
  document.getElementById("navReleases").textContent = copy.releases;
  document.getElementById("themeLabel").textContent = copy.theme;
  document.getElementById("languageLabel").textContent = copy.language;
  document.getElementById("backToWorkspace").textContent = copy.back;
  document.getElementById("footerBack").textContent = copy.footerBack;

  if (!data) return;
  const current = data.releases?.find((item) => item.version === data.current_version) || data.releases?.[0];
  const workflow = data.workflow?.[releaseState.language] || data.workflow?.en || [];
  const features = (data.features || [])
    .map(
      (feature) => `
        <article class="feature-card" id="feature-${escapeReleaseHtml(feature.id)}">
          <span class="feature-index">${escapeReleaseHtml(feature.icon)}</span>
          <h3>${escapeReleaseHtml(localized(feature.title))}</h3>
          <p>${escapeReleaseHtml(localized(feature.summary))}</p>
          ${renderList(feature.bullets?.[releaseState.language] || feature.bullets?.en)}
        </article>`,
    )
    .join("");
  const releases = (data.releases || [])
    .map(
      (release) => `
        <article class="release-entry">
          <div class="release-entry-head">
            <div>
              <span class="version-chip">v${escapeReleaseHtml(release.version)}</span>
              <time datetime="${escapeReleaseHtml(release.date)}">${escapeReleaseHtml(release.date)}</time>
            </div>
            <h3>${escapeReleaseHtml(localized(release.name))}</h3>
            <p>${escapeReleaseHtml(localized(release.summary))}</p>
          </div>
          <div class="release-sections">
            ${(release.sections || [])
              .map(
                (section) => `
                  <section class="release-section release-${escapeReleaseHtml(section.key)}">
                    <h4>${escapeReleaseHtml(localized(section.title))}</h4>
                    ${renderList(section.items?.[releaseState.language] || section.items?.en)}
                  </section>`,
              )
              .join("")}
          </div>
        </article>`,
    )
    .join("");

  document.getElementById("releaseApp").innerHTML = `
    <section id="overview" class="release-hero">
      <div class="hero-release-copy">
        <p class="release-eyebrow">${escapeReleaseHtml(copy.eyebrow)} · v${escapeReleaseHtml(data.current_version)}</p>
        <h1>${escapeReleaseHtml(copy.heroTitle)}</h1>
        <p class="release-lead">${escapeReleaseHtml(copy.heroBody)}</p>
        <div class="release-hero-actions">
          <a class="primary-link" href="#features">${escapeReleaseHtml(copy.explore)}</a>
          <a class="secondary-link" href="#releases">${escapeReleaseHtml(copy.readRelease)}</a>
        </div>
      </div>
      <aside class="current-release-card">
        <span>v${escapeReleaseHtml(current?.version || data.current_version)}</span>
        <h2>${escapeReleaseHtml(localized(current?.name))}</h2>
        <p>${escapeReleaseHtml(localized(current?.summary))}</p>
        <time datetime="${escapeReleaseHtml(current?.date)}">${escapeReleaseHtml(current?.date)}</time>
      </aside>
    </section>

    <section class="workflow-section">
      <div class="section-intro">
        <h2>${escapeReleaseHtml(copy.workflowTitle)}</h2>
        <p>${escapeReleaseHtml(copy.workflowBody)}</p>
      </div>
      <ol class="workflow-grid">
        ${workflow.map((step, index) => `<li><span>${index + 1}</span><p>${escapeReleaseHtml(step)}</p></li>`).join("")}
      </ol>
    </section>

    <section id="features" class="feature-section">
      <div class="section-intro">
        <h2>${escapeReleaseHtml(copy.featureTitle)}</h2>
        <p>${escapeReleaseHtml(copy.featureBody)}</p>
      </div>
      <div class="feature-grid">${features}</div>
    </section>

    <section id="releases" class="release-history">
      <div class="section-intro">
        <h2>${escapeReleaseHtml(copy.releaseTitle)}</h2>
        <p>${escapeReleaseHtml(copy.releaseBody)}</p>
      </div>
      ${releases}
    </section>`;
}

async function loadReleasePage() {
  try {
    const response = await fetch("/ui/releases.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    releaseState.data = await response.json();
    renderReleasePage();
  } catch (error) {
    document.getElementById("releaseApp").innerHTML = `<section class="release-loading"><p>${escapeReleaseHtml(releaseCopy[releaseState.language].loadError)}</p></section>`;
  }
}

const languageSelect = document.getElementById("releaseLanguage");
const themeSelect = document.getElementById("releaseTheme");
languageSelect.value = releaseState.language;
themeSelect.value = releaseState.theme;
languageSelect.addEventListener("change", () => {
  releaseState.language = languageSelect.value;
  localStorage.setItem("docugenLanguage", releaseState.language);
  renderReleasePage();
});
themeSelect.addEventListener("change", () => {
  releaseState.theme = themeSelect.value;
  localStorage.setItem("docugenTheme", releaseState.theme);
  document.documentElement.dataset.theme = releaseState.theme;
});

renderReleasePage();
loadReleasePage();
