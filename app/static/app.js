const state = {
  projects: [],
  selectedProjectId: null,
  progressTimer: null,
  activeTab: "questions",
  draftView: "rendered",
  language: localStorage.getItem("docugenLanguage") || "en",
  theme: localStorage.getItem("docugenTheme") || "simpsons",
  questions: [],
  answerDrafts: {},
  artifacts: [],
  progress: null,
};

const translations = {
  en: {
    add: "Add",
    addQuestion: "Add Question",
    all: "All",
    answer: "Answer",
    answerDeleted: "Answer deleted.",
    answered: "Answered",
    answerNotAvailable: "(answer not available)",
    answerSaved: "Answer saved.",
    answerUpdated: "Answer updated. Older artifacts will be regenerated on the next run.",
    appTitle: "LLM Document Agent",
    artifactSaved: "Artifact saved.",
    artifacts: "Artifacts",
    audience: "Audience",
    changed: "Changed",
    chapters: "Chapters",
    characters: "Characters",
    checkingApi: "Checking API status",
    completed: "completed",
    createProject: "Create Project",
    created: "created",
    contents: "Contents",
    currentProject: "Current Project",
    delete: "Delete",
    deleteAnswer: "Delete Answer",
    deleteAnswerConfirm: "Delete this answer and make the question pending again?",
    deleteProjectConfirm:
      'Delete "{title}"? This will remove its questions, answers, artifacts, summaries, and run logs.',
    draftEmpty: "Run the pipeline to generate a draft.",
    draftPreview: "Draft Preview",
    duration: "Duration",
    editAnswer: "Edit Answer",
    emptyBody: "Choose a project from the sidebar, or create a new one to start the writing pipeline.",
    emptyTitle: "Select or create a project",
    error: "Error",
    export: "Export",
    exportedTo: "Exported to {path}",
    finalMerge: "Final merge",
    goal: "Goal",
    idle: "Idle",
    initialRequest: "Initial request",
    jsonContent: "JSON content",
    language: "Language",
    mode: "Mode",
    new: "New",
    nextAction: "Next Action",
    noArtifacts: "No artifacts.",
    noDraft: "No draft",
    noProjects: "No projects yet.",
    noQuestions: "No questions.",
    notStarted: "Not started yet.",
    notes: "Notes",
    pending: "Pending",
    phase: "Phase",
    pipeline: "Pipeline",
    pipelineDetails: "Pipeline Details",
    pipelineFailed: "Pipeline failed",
    pipelineFailedBody: "Check the Pipeline tab for the failed step, then retry after fixing the issue.",
    projectCreated: "Project created.",
    projectDeleted: "Project deleted.",
    projects: "Projects",
    query: "Query",
    question: "Question",
    questionAdded: "Question added.",
    questions: "Questions",
    raw: "Raw",
    ready: "Ready",
    readyBody: "Start the writing pipeline when you are ready.",
    refresh: "Refresh",
    refreshed: "Refreshed.",
    rendered: "Rendered",
    reranFrom: "Reran from {phase}.",
    rerunConfirm: "Rerun from {phase}? Downstream artifacts will be regenerated.",
    rerunFromHere: "Rerun from here",
    reviewDraft: "Review the draft",
    reviewDraftBody: "The staged pipeline completed. Review the draft preview or inspect intermediate artifacts.",
    saveArtifact: "Save Artifact",
    searchError: "Search error",
    sections: "Sections",
    sectionDrafts: "Section drafts",
    sourceSummaries: "Source summaries",
    sources: "Sources",
    started: "started",
    startWriting: "Start Writing",
    startWritingAction: "Start writing",
    startWritingActionBody: "Run the staged pipeline to ask intake questions or generate section-level drafts.",
    summaries: "Summaries",
    theme: "Theme",
    themePastel: "Pastel Watercolor",
    themeSimpsons: "Simpsons",
    title: "Title",
    tone: "Tone",
    topic: "Topic",
    type: "Type",
    updateAnswer: "Update answer",
    updated: "updated",
    verdict: "Verdict",
    writing: "Writing...",
    writingInProgress: "Writing in progress",
    writingInProgressBody: "The pipeline is moving through brief, outline, section drafts, summaries, and final merge.",
    writerNeedsInput:
      "The writer needs your input before continuing. Answer pending questions, then start writing again.",
  },
  ko: {
    add: "추가",
    addQuestion: "질문 추가",
    all: "전체",
    answer: "답변",
    answerDeleted: "답변을 삭제했습니다.",
    answered: "답변 완료",
    answerNotAvailable: "(답변을 불러올 수 없음)",
    answerSaved: "답변을 저장했습니다.",
    answerUpdated: "답변을 수정했습니다. 다음 실행 시 이전 산출물이 다시 생성됩니다.",
    appTitle: "LLM 문서 작성 에이전트",
    artifactSaved: "산출물을 저장했습니다.",
    artifacts: "산출물",
    audience: "대상 독자",
    changed: "변경 여부",
    chapters: "목차",
    characters: "문자 수",
    checkingApi: "API 상태 확인 중",
    completed: "완료",
    createProject: "프로젝트 생성",
    created: "생성",
    contents: "목차",
    currentProject: "현재 프로젝트",
    delete: "삭제",
    deleteAnswer: "답변 삭제",
    deleteAnswerConfirm: "이 답변을 삭제하고 질문을 다시 대기 상태로 바꿀까요?",
    deleteProjectConfirm:
      '"{title}" 프로젝트를 삭제할까요? 질문, 답변, 산출물, 요약, 실행 로그가 모두 삭제됩니다.',
    draftEmpty: "파이프라인을 실행하면 초안이 생성됩니다.",
    draftPreview: "초안 미리보기",
    duration: "소요 시간",
    editAnswer: "답변 수정",
    emptyBody: "왼쪽에서 프로젝트를 선택하거나 새 프로젝트를 만들어 작성 파이프라인을 시작하세요.",
    emptyTitle: "프로젝트를 선택하거나 생성하세요",
    error: "오류",
    export: "내보내기",
    exportedTo: "{path}로 내보냈습니다.",
    finalMerge: "최종 병합",
    goal: "목표",
    idle: "대기",
    initialRequest: "초기 요청",
    jsonContent: "JSON 내용",
    language: "언어",
    mode: "모드",
    new: "새로 만들기",
    nextAction: "다음 작업",
    noArtifacts: "산출물이 없습니다.",
    noDraft: "초안 없음",
    noProjects: "아직 프로젝트가 없습니다.",
    noQuestions: "질문이 없습니다.",
    notStarted: "아직 시작하지 않았습니다.",
    notes: "메모",
    pending: "대기",
    phase: "단계",
    pipeline: "파이프라인",
    pipelineDetails: "파이프라인 상세",
    pipelineFailed: "파이프라인 실패",
    pipelineFailedBody: "파이프라인 탭에서 실패한 단계를 확인한 뒤 문제를 해결하고 다시 실행하세요.",
    projectCreated: "프로젝트를 생성했습니다.",
    projectDeleted: "프로젝트를 삭제했습니다.",
    projects: "프로젝트",
    query: "검색어",
    question: "질문",
    questionAdded: "질문을 추가했습니다.",
    questions: "질문",
    raw: "원문",
    ready: "준비됨",
    readyBody: "준비되면 작성 파이프라인을 시작하세요.",
    refresh: "새로고침",
    refreshed: "새로고침했습니다.",
    rendered: "서식 보기",
    reranFrom: "{phase} 단계부터 다시 실행했습니다.",
    rerunConfirm: "{phase} 단계부터 다시 실행할까요? 이후 산출물은 다시 생성됩니다.",
    rerunFromHere: "여기서부터 재실행",
    reviewDraft: "초안 검토",
    reviewDraftBody: "단계별 파이프라인이 완료되었습니다. 초안 미리보기나 중간 산출물을 검토하세요.",
    saveArtifact: "산출물 저장",
    searchError: "검색 오류",
    sections: "섹션",
    sectionDrafts: "섹션 초안",
    sourceSummaries: "출처 요약",
    sources: "출처",
    started: "시작",
    startWriting: "작성 시작",
    startWritingAction: "작성 시작",
    startWritingActionBody: "질문을 생성하거나 섹션 단위 초안을 만들기 위해 단계별 파이프라인을 실행하세요.",
    summaries: "요약",
    theme: "테마",
    themePastel: "파스텔 수채화",
    themeSimpsons: "심슨 만화",
    title: "제목",
    tone: "톤",
    topic: "주제",
    type: "유형",
    updateAnswer: "답변 수정",
    updated: "수정",
    verdict: "판정",
    writing: "작성 중...",
    writingInProgress: "작성 진행 중",
    writingInProgressBody: "브리프, 목차, 섹션 초안, 요약, 최종 병합 단계가 진행 중입니다.",
    writerNeedsInput: "계속 작성하기 전에 입력이 필요합니다. 대기 중인 질문에 답한 뒤 다시 작성하세요.",
  },
};

const phaseLabels = {
  en: {
    intake: "Intake questions",
    research: "Web research",
    source_summary: "Source summaries",
    brief: "Brief",
    outline: "Outline",
    outline_review: "Outline review",
    section_plan: "Section plan",
    section_plan_review: "Section plan review",
    chapter_research: "Chapter research",
    section_writing: "Section writing",
    section_summary: "Section summaries",
    continuity_review: "Continuity review",
    targeted_revision: "Targeted revision",
    final_merge: "Final merge",
  },
  ko: {
    intake: "질문 수집",
    research: "웹 검색",
    source_summary: "출처 요약",
    brief: "작성 브리프",
    outline: "목차 생성",
    outline_review: "목차 검토",
    section_plan: "섹션 계획",
    section_plan_review: "섹션 계획 검토",
    chapter_research: "챕터 자료 조사",
    section_writing: "섹션 작성",
    section_summary: "섹션 요약",
    continuity_review: "흐름 검토",
    targeted_revision: "부분 수정",
    final_merge: "최종 병합",
  },
};

const workflowPhases = Object.keys(phaseLabels.en);

const els = {
  healthText: document.querySelector("#healthText"),
  refreshButton: document.querySelector("#refreshButton"),
  runButton: document.querySelector("#runButton"),
  deleteProjectButton: document.querySelector("#deleteProjectButton"),
  newProjectToggle: document.querySelector("#newProjectToggle"),
  projectForm: document.querySelector("#projectForm"),
  projectTitle: document.querySelector("#projectTitle"),
  projectRequest: document.querySelector("#projectRequest"),
  projectList: document.querySelector("#projectList"),
  projectCount: document.querySelector("#projectCount"),
  emptyState: document.querySelector("#emptyState"),
  projectDetail: document.querySelector("#projectDetail"),
  detailTitle: document.querySelector("#detailTitle"),
  detailMeta: document.querySelector("#detailMeta"),
  detailStatus: document.querySelector("#detailStatus"),
  nextAction: document.querySelector("#nextAction"),
  nextActionTitle: document.querySelector("#nextActionTitle"),
  nextActionBody: document.querySelector("#nextActionBody"),
  nextActionItems: document.querySelector("#nextActionItems"),
  progressPercent: document.querySelector("#progressPercent"),
  progressFill: document.querySelector("#progressFill"),
  progressSteps: document.querySelector("#progressSteps"),
  draftStatus: document.querySelector("#draftStatus"),
  draftToc: document.querySelector("#draftToc"),
  draftPreview: document.querySelector("#draftPreview"),
  draftViewToggle: document.querySelector("#draftViewToggle"),
  exportButton: document.querySelector("#exportButton"),
  questionForm: document.querySelector("#questionForm"),
  questionPhase: document.querySelector("#questionPhase"),
  questionText: document.querySelector("#questionText"),
  questionFilter: document.querySelector("#questionFilter"),
  questionList: document.querySelector("#questionList"),
  addQuestionToggle: document.querySelector("#addQuestionToggle"),
  artifactForm: document.querySelector("#artifactForm"),
  artifactType: document.querySelector("#artifactType"),
  artifactTitle: document.querySelector("#artifactTitle"),
  artifactContent: document.querySelector("#artifactContent"),
  artifactList: document.querySelector("#artifactList"),
  artifactCount: document.querySelector("#artifactCount"),
  addArtifactToggle: document.querySelector("#addArtifactToggle"),
  pipelineStatus: document.querySelector("#pipelineStatus"),
  pipelineList: document.querySelector("#pipelineList"),
  toast: document.querySelector("#toast"),
  languageSelect: document.querySelector("#languageSelect"),
  themeSelect: document.querySelector("#themeSelect"),
};

function applyTheme() {
  document.documentElement.dataset.theme = state.theme;
  if (els.themeSelect) {
    els.themeSelect.value = state.theme;
  }
}

function t(key, params = {}) {
  const template = translations[state.language]?.[key] || translations.en[key] || key;
  return Object.entries(params).reduce(
    (text, [name, value]) => text.replaceAll(`{${name}}`, String(value)),
    template,
  );
}

function statusLabel(status) {
  const normalized = String(status || "");
  return translations[state.language]?.[normalized] || normalized;
}

function phaseLabel(phase, fallback = "") {
  const normalized = String(phase || "");
  return phaseLabels[state.language]?.[normalized] || fallback || normalized || "-";
}

function applyStaticTranslations() {
  document.documentElement.lang = state.language;
  if (els.languageSelect) {
    els.languageSelect.value = state.language;
  }
  for (const node of document.querySelectorAll("[data-i18n]")) {
    node.textContent = t(node.dataset.i18n);
  }
  els.languageSelect?.setAttribute("aria-label", t("language"));
  els.themeSelect?.setAttribute("aria-label", t("theme"));
  els.questionFilter?.setAttribute("aria-label", t("questions"));
  if (els.themeSelect) {
    els.themeSelect.value = state.theme;
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
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

function showToast(message, isError = false) {
  els.toast.textContent = message;
  els.toast.classList.toggle("error", isError);
  els.toast.classList.remove("hidden");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => els.toast.classList.add("hidden"), 2800);
}

function formatDate(value) {
  if (!value) return "-";
  return new Intl.DateTimeFormat(state.language === "ko" ? "ko-KR" : "en-US", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatDuration(milliseconds) {
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return "-";
  const seconds = Math.round(milliseconds / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const restSeconds = seconds % 60;
  if (minutes < 60) return `${minutes}m ${restSeconds}s`;
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  return `${hours}h ${restMinutes}m`;
}

function stepDuration(step) {
  if (!step.created_at) return "-";
  const start = new Date(step.created_at).getTime();
  const end = step.completed_at ? new Date(step.completed_at).getTime() : Date.now();
  return formatDuration(end - start);
}

function selectedProject() {
  return state.projects.find((project) => project.id === state.selectedProjectId) || null;
}

function latestDraft() {
  return state.artifacts.find((artifact) => artifact.type === "draft") || null;
}

function answerDraftKey(questionId) {
  return `${state.selectedProjectId || "none"}:${questionId}`;
}

function getAnswerDraft(questionId) {
  const key = answerDraftKey(questionId);
  return Object.prototype.hasOwnProperty.call(state.answerDrafts, key)
    ? state.answerDrafts[key]
    : "";
}

function setAnswerDraft(questionId, value) {
  state.answerDrafts[answerDraftKey(questionId)] = value;
}

function clearAnswerDraft(questionId) {
  delete state.answerDrafts[answerDraftKey(questionId)];
}

function pruneAnswerDrafts() {
  const projectPrefix = `${state.selectedProjectId || "none"}:`;
  const pendingIds = new Set(
    state.questions
      .filter((question) => question.status === "pending")
      .map((question) => question.id),
  );

  for (const key of Object.keys(state.answerDrafts)) {
    if (!key.startsWith(projectPrefix)) continue;
    const questionId = key.slice(projectPrefix.length);
    if (!pendingIds.has(questionId)) {
      delete state.answerDrafts[key];
    }
  }
}

async function loadHealth() {
  const health = await api("/health");
  els.healthText.textContent = `API ${health.status} - ${health.env}`;
}

async function loadProjects() {
  state.projects = await api("/projects");
  els.projectCount.textContent =
    state.language === "ko"
      ? `${state.projects.length}개 프로젝트`
      : `${state.projects.length} project${state.projects.length === 1 ? "" : "s"}`;

  if (!state.selectedProjectId && state.projects.length > 0) {
    state.selectedProjectId = state.projects[0].id;
  }

  if (
    state.selectedProjectId &&
    !state.projects.some((project) => project.id === state.selectedProjectId)
  ) {
    state.selectedProjectId = state.projects[0]?.id || null;
  }

  renderProjects();
  await renderSelectedProject();
}

function renderProjects() {
  els.projectList.innerHTML = "";

  if (state.projects.length === 0) {
    els.projectList.innerHTML = `<p class="item-meta">${escapeHtml(t("noProjects"))}</p>`;
    return;
  }

  for (const project of state.projects) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "project-item";
    button.classList.toggle("active", project.id === state.selectedProjectId);
    button.innerHTML = `
      <p class="item-title"></p>
      <p class="item-meta"></p>
    `;
    button.querySelector(".item-title").textContent = project.title;
    button.querySelector(".item-meta").textContent =
      `${statusLabel(project.status)} - ${phaseLabel(project.current_phase)} - ${formatDate(project.updated_at)}`;
    button.addEventListener("click", async () => {
      state.selectedProjectId = project.id;
      renderProjects();
      await renderSelectedProject();
    });
    els.projectList.append(button);
  }
}

async function renderSelectedProject() {
  const project = selectedProject();

  els.emptyState.classList.toggle("hidden", Boolean(project));
  els.projectDetail.classList.toggle("hidden", !project);

  if (!project) return;

  els.detailTitle.textContent = project.title;
  els.detailMeta.textContent =
    `${phaseLabel(project.current_phase)} - ${t("created")} ${formatDate(project.created_at)} - ${t("updated")} ${formatDate(project.updated_at)}`;
  els.detailStatus.textContent = statusLabel(project.status);

  await Promise.all([loadProgress(), loadQuestions(), loadArtifacts()]);
  renderNextAction();
  renderDraftPreview();
  renderTabs();

  if (state.progress?.status === "running") {
    if (!state.progressTimer) startRunPolling();
  } else if (!state.progressTimer) {
    setRunButtonRunning(false);
  }
}

async function loadProgress() {
  const project = selectedProject();
  if (!project) return;

  state.progress = await api(`/projects/${project.id}/progress`);
  renderProgress();
}

function renderProgress() {
  const progress = state.progress;
  if (!progress) return;

  els.progressPercent.textContent = `${progress.percent}%`;
  els.progressFill.style.width = `${progress.percent}%`;
  els.pipelineStatus.textContent = statusLabel(progress.status);
  els.progressSteps.innerHTML = "";
  els.pipelineList.innerHTML = "";

  for (const step of progress.steps) {
    const compact = document.createElement("div");
    compact.className = `progress-step ${step.status}`;
    compact.innerHTML = `
      <strong></strong>
      <span></span>
    `;
    compact.querySelector("strong").textContent = phaseLabel(step.phase, step.label);
    compact.querySelector("span").textContent = `${statusLabel(step.status)} · ${stepDuration(step)}`;
    if (step.error) compact.title = step.error;
    els.progressSteps.append(compact);

    const detail = document.createElement("article");
    detail.className = "item";
    detail.innerHTML = `
      <div class="item-head">
        <p class="item-title"></p>
        <button type="button" class="secondary rerun-step">${escapeHtml(t("rerunFromHere"))}</button>
      </div>
      <p class="item-meta"></p>
      <p class="item-body"></p>
    `;
    detail.querySelector(".item-title").textContent = phaseLabel(step.phase, step.label);
    detail.querySelector(".item-meta").textContent =
      `${statusLabel(step.status)} - ${t("started")} ${formatDate(step.created_at)} - ${t("completed")} ${formatDate(step.completed_at)} - ${t("duration")} ${stepDuration(step)}`;
    detail.querySelector(".item-body").innerHTML = renderStepDetails(step);
    detail.querySelector(".rerun-step").addEventListener("click", () => {
      rerunFromStep(step.phase).catch((error) => showToast(error.message, true));
    });
    els.pipelineList.append(detail);
  }
}

function resetProgressForRun(startPhase = "intake") {
  const startIndex = Math.max(0, workflowPhases.indexOf(startPhase));
  const startedAt = new Date().toISOString();
  state.progress = {
    project: selectedProject(),
    percent: startIndex === 0 ? 0 : Math.floor((startIndex / workflowPhases.length) * 100),
    current_phase: startPhase,
    status: "running",
    steps: workflowPhases.map((phase, index) => ({
      phase,
      label: phaseLabel(phase),
      status: index < startIndex ? "completed" : index === startIndex ? "running" : "pending",
      created_at: index === startIndex ? startedAt : null,
      completed_at: null,
      error: null,
      details: {},
    })),
  };
  renderProgress();
}

function stopRunPolling() {
  window.clearInterval(state.progressTimer);
  state.progressTimer = null;
}

function setRunButtonRunning(isRunning) {
  els.runButton.disabled = isRunning;
  els.runButton.textContent = isRunning ? t("writing") : t("startWriting");
}

function startRunPolling() {
  stopRunPolling();
  setRunButtonRunning(true);
  state.progressTimer = window.setInterval(async () => {
    try {
      await loadProgress();
    } catch {
      return;
    }
    const status = state.progress?.status;
    if (status && status !== "running") {
      stopRunPolling();
      setRunButtonRunning(false);
      await loadProjects().catch(() => {});
    }
  }, 1200);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function inlineMarkdown(value) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(
      /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noreferrer">$1</a>',
    );
}

function slugifyHeading(value, counts) {
  const base = String(value || "")
    .toLowerCase()
    .replace(/<[^>]+>/g, "")
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .trim()
    .replace(/\s+/g, "-")
    .slice(0, 80) || "section";
  counts[base] = (counts[base] || 0) + 1;
  return counts[base] === 1 ? base : `${base}-${counts[base]}`;
}

function renderToc(toc) {
  if (!toc.length) return "";
  return `
    <p class="draft-toc-title">${escapeHtml(t("contents"))}</p>
    <nav>
      ${toc
        .map(
          (item) =>
            `<a class="toc-level-${item.level}" href="#${escapeHtml(item.id)}">${escapeHtml(item.text)}</a>`,
        )
        .join("")}
    </nav>
  `;
}

function renderMarkdown(markdown) {
  const lines = String(markdown || "").replace(/\r\n/g, "\n").split("\n");
  const html = [];
  const toc = [];
  const headingCounts = {};
  let paragraph = [];
  let listOpen = false;
  let orderedListOpen = false;
  let blockquote = [];
  let codeOpen = false;
  let codeLines = [];

  function flushParagraph() {
    if (paragraph.length === 0) return;
    html.push(`<p>${inlineMarkdown(paragraph.join(" "))}</p>`);
    paragraph = [];
  }

  function closeList() {
    if (!listOpen) return;
    html.push("</ul>");
    listOpen = false;
  }

  function closeOrderedList() {
    if (!orderedListOpen) return;
    html.push("</ol>");
    orderedListOpen = false;
  }

  function flushBlockquote() {
    if (blockquote.length === 0) return;
    html.push(`<blockquote>${blockquote.map((line) => `<p>${inlineMarkdown(line)}</p>`).join("")}</blockquote>`);
    blockquote = [];
  }

  function closeCode() {
    if (!codeOpen) return;
    html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
    codeLines = [];
    codeOpen = false;
  }

  function splitTableRow(row) {
    return row
      .trim()
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map((cell) => cell.trim());
  }

  function isTableSeparator(row) {
    const cells = splitTableRow(row);
    return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s/g, "")));
  }

  function renderTable(headers, rows) {
    const headerHtml = headers.map((header) => `<th>${inlineMarkdown(header)}</th>`).join("");
    const rowHtml = rows
      .map((row) => {
        const cells = headers.map((_, index) => `<td>${inlineMarkdown(row[index] || "")}</td>`).join("");
        return `<tr>${cells}</tr>`;
      })
      .join("");
    return `<div class="table-scroll"><table><thead><tr>${headerHtml}</tr></thead><tbody>${rowHtml}</tbody></table></div>`;
  }

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (line.trim().startsWith("```")) {
      if (codeOpen) {
        closeCode();
      } else {
        flushParagraph();
        closeList();
        closeOrderedList();
        flushBlockquote();
        codeOpen = true;
      }
      continue;
    }

    if (codeOpen) {
      codeLines.push(line);
      continue;
    }

    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      closeList();
      closeOrderedList();
      flushBlockquote();
      continue;
    }

    const nextLine = lines[index + 1]?.trim() || "";
    if (trimmed.includes("|") && isTableSeparator(nextLine)) {
      flushParagraph();
      closeList();
      closeOrderedList();
      flushBlockquote();
      const headers = splitTableRow(trimmed);
      const rows = [];
      index += 2;
      while (index < lines.length) {
        const rowLine = lines[index].trim();
        if (!rowLine || !rowLine.includes("|") || rowLine.startsWith("```")) {
          index -= 1;
          break;
        }
        rows.push(splitTableRow(rowLine));
        index += 1;
      }
      html.push(renderTable(headers, rows));
      continue;
    }

    const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      closeList();
      closeOrderedList();
      flushBlockquote();
      const level = heading[1].length;
      const text = heading[2].trim();
      const id = slugifyHeading(text, headingCounts);
      toc.push({ id, level, text });
      html.push(`<h${level} id="${escapeHtml(id)}">${inlineMarkdown(text)}</h${level}>`);
      continue;
    }

    const bullet = trimmed.match(/^[-*]\s+(.+)$/);
    if (bullet) {
      flushParagraph();
      closeOrderedList();
      flushBlockquote();
      if (!listOpen) {
        html.push("<ul>");
        listOpen = true;
      }
      html.push(`<li>${inlineMarkdown(bullet[1])}</li>`);
      continue;
    }

    const numbered = trimmed.match(/^\d+\.\s+(.+)$/);
    if (numbered) {
      flushParagraph();
      closeList();
      flushBlockquote();
      if (!orderedListOpen) {
        html.push("<ol>");
        orderedListOpen = true;
      }
      html.push(`<li>${inlineMarkdown(numbered[1])}</li>`);
      continue;
    }

    const quote = trimmed.match(/^>\s?(.+)$/);
    if (quote) {
      flushParagraph();
      closeList();
      closeOrderedList();
      blockquote.push(quote[1]);
      continue;
    }

    paragraph.push(trimmed);
  }

  closeCode();
  flushParagraph();
  closeList();
  closeOrderedList();
  flushBlockquote();
  return {
    html: html.join("\n") || `<p>${escapeHtml(t("draftEmpty"))}</p>`,
    toc,
  };
}

function renderKeyValueList(items) {
  return `<dl class="detail-list">${items
    .filter((item) => item[1] !== undefined && item[1] !== null && item[1] !== "")
    .map(([key, value]) => `<div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd></div>`)
    .join("")}</dl>`;
}

function renderBullets(items) {
  if (!items || items.length === 0) return "";
  return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function renderStepDetails(step) {
  const details = step.details || {};
  if (step.error) {
    return `<strong>${escapeHtml(t("error"))}</strong><p>${escapeHtml(step.error)}</p>`;
  }

  if (step.status === "pending" && Object.keys(details).length === 0) {
    return t("notStarted");
  }

  switch (step.phase) {
    case "research":
      return [
        renderKeyValueList([
          [t("query"), details.query],
          [t("sources"), details.source_count],
          [t("searchError"), details.error],
        ]),
        details.sources?.length
          ? `<ul>${details.sources
              .map(
                (source) =>
                  `<li><a href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer">${escapeHtml(source.title || source.url)}</a></li>`,
              )
              .join("")}</ul>`
          : "",
      ].join("");
    case "source_summary":
      return [
        renderKeyValueList([[t("sourceSummaries"), details.source_summary_count]]),
        `<div class="preview-list">${(details.source_summaries || [])
          .map(
            (source) =>
              `<article><strong>${escapeHtml(source.title || source.url)}</strong><p>${escapeHtml(source.summary || source.error || "")}</p></article>`,
          )
          .join("")}</div>`,
      ].join("");
    case "brief":
      return renderKeyValueList([
        [t("topic"), details.brief?.topic],
        [t("goal"), details.brief?.goal],
        [t("audience"), details.brief?.audience],
        [t("tone"), details.brief?.tone],
      ]);
    case "outline":
      return [
        renderKeyValueList([[t("chapters"), details.chapter_count]]),
        renderBullets(details.chapters),
      ].join("");
    case "outline_review":
    case "section_plan_review":
    case "continuity_review":
      return [
        renderKeyValueList([
          [t("verdict"), details.verdict],
          [t("notes"), details.notes],
        ]),
        renderBullets(details.issues),
      ].join("");
    case "section_plan":
      return [
        renderKeyValueList([
          [t("chapters"), details.tree_root_count],
          [t("sections"), details.section_count],
        ]),
        `<ul>${(details.sections || [])
          .map(
            (section) =>
              `<li>${escapeHtml(section.id)} ${escapeHtml(section.path || section.title)}${section.depth ? ` · depth ${escapeHtml(section.depth)}` : ""}</li>`,
          )
          .join("")}</ul>`,
      ].join("");
    case "section_writing":
      return [
        renderKeyValueList([[t("sectionDrafts"), details.section_draft_count]]),
        `<div class="preview-list">${(details.section_drafts || [])
          .map(
            (draft) =>
              `<article><strong>${escapeHtml(draft.title)}</strong><p>${escapeHtml(draft.preview)}</p></article>`,
          )
          .join("")}</div>`,
      ].join("");
    case "section_summary":
      return [
        renderKeyValueList([
          [t("summaries"), details.summary_count],
          [t("mode"), details.summary_mode],
        ]),
        `<div class="preview-list">${(details.summaries || [])
          .map(
            (summary) =>
              `<article><strong>${escapeHtml(summary.section_id)}</strong><p>${escapeHtml(summary.summary)}</p></article>`,
          )
          .join("")}</div>`,
      ].join("");
    case "targeted_revision":
      return renderKeyValueList([
        [t("changed"), details.changed],
        [t("sections"), details.section_count],
      ]);
    case "final_merge":
      return [
        renderKeyValueList([
          [t("mode"), details.merge_mode],
          [t("characters"), details.character_count],
        ]),
        details.draft_preview ? `<pre class="mini-preview">${escapeHtml(details.draft_preview)}</pre>` : "",
      ].join("");
    default:
      return details.output ? `<pre class="mini-preview">${escapeHtml(JSON.stringify(details.output, null, 2))}</pre>` : step.phase;
  }
}

async function loadQuestions() {
  const project = selectedProject();
  if (!project) return;

  const status = els.questionFilter.value;
  state.questions = await api(
    `/projects/${project.id}/questions${status ? `?status=${encodeURIComponent(status)}` : ""}`,
  );
  pruneAnswerDrafts();
  renderQuestions();
}

function renderQuestions() {
  els.questionList.innerHTML = "";

  if (state.questions.length === 0) {
    els.questionList.innerHTML = `<p class="item-meta">${escapeHtml(t("noQuestions"))}</p>`;
    return;
  }

  const sorted = [...state.questions].sort((a, b) => {
    if (a.status === b.status) return 0;
    return a.status === "pending" ? -1 : 1;
  });

  for (const question of sorted) {
    const item = document.createElement("article");
    item.className = "item";
    const questionText =
      typeof question.question.question === "string"
        ? question.question.question
        : JSON.stringify(question.question, null, 2);
    item.innerHTML = `
      <p class="item-title"></p>
      <p class="item-meta"></p>
      <p class="item-body"></p>
    `;
    item.querySelector(".item-title").textContent = question.phase;
    item.querySelector(".item-meta").textContent =
      `${statusLabel(question.status)} - ${t("created")} ${formatDate(question.created_at)}${question.answered_at ? ` - ${t("answered")} ${formatDate(question.answered_at)}` : ""}`;
    item.querySelector(".item-body").textContent = questionText;

    if (question.status === "pending") {
      const answerRow = document.createElement("form");
      answerRow.className = "answer-row";
      answerRow.innerHTML = `
        <input aria-label="${escapeHtml(t("answer"))}" required placeholder="${escapeHtml(t("answer"))}" />
        <button type="submit">${escapeHtml(t("answer"))}</button>
      `;
      const input = answerRow.querySelector("input");
      input.value = getAnswerDraft(question.id);
      input.addEventListener("input", () => {
        setAnswerDraft(question.id, input.value);
      });
      answerRow.addEventListener("submit", async (event) => {
        event.preventDefault();
        await answerQuestion(question.id, input.value);
      });
      item.append(answerRow);
    } else {
      const answerPreview = document.createElement("p");
      answerPreview.className = "answer-preview";
      answerPreview.textContent = `${t("answer")}: ${question.answer || t("answerNotAvailable")}`;
      item.append(answerPreview);

      const actionRow = document.createElement("div");
      actionRow.className = "answer-actions";
      actionRow.innerHTML = `
        <button type="button" class="secondary edit-answer">${escapeHtml(t("editAnswer"))}</button>
        <button type="button" class="danger delete-answer">${escapeHtml(t("deleteAnswer"))}</button>
      `;
      actionRow.querySelector(".edit-answer").addEventListener("click", async () => {
        const nextAnswer = window.prompt(t("updateAnswer"), question.answer || "");
        if (!nextAnswer) return;
        await updateAnswer(question.id, nextAnswer);
      });
      actionRow.querySelector(".delete-answer").addEventListener("click", async () => {
        if (!window.confirm(t("deleteAnswerConfirm"))) return;
        await deleteAnswer(question.id);
      });
      item.append(actionRow);
    }

    els.questionList.append(item);
  }
}

async function answerQuestion(questionId, answer) {
  const project = selectedProject();
  if (!project) return;

  await api(`/projects/${project.id}/questions/${questionId}/answer`, {
    method: "POST",
    body: JSON.stringify({ answer }),
  });
  clearAnswerDraft(questionId);
  showToast(t("answerSaved"));
  await Promise.all([loadQuestions(), loadProjects()]);
}

async function updateAnswer(questionId, answer) {
  const project = selectedProject();
  if (!project) return;
  await api(`/projects/${project.id}/questions/${questionId}/answer`, {
    method: "PUT",
    body: JSON.stringify({ answer }),
  });
  showToast(t("answerUpdated"));
  await Promise.all([loadQuestions(), loadProjects()]);
}

async function deleteAnswer(questionId) {
  const project = selectedProject();
  if (!project) return;
  await api(`/projects/${project.id}/questions/${questionId}/answer`, {
    method: "DELETE",
  });
  clearAnswerDraft(questionId);
  showToast(t("answerDeleted"));
  await Promise.all([loadQuestions(), loadProjects()]);
}

function artifactBodyText(artifact) {
  if (artifact.type === "draft" && artifact.content?.markdown) {
    return artifact.content.markdown;
  }
  if (artifact.type === "section_draft" && artifact.content?.markdown) {
    return artifact.content.markdown;
  }
  return JSON.stringify(artifact.content || {}, null, 2);
}

async function loadArtifacts() {
  const project = selectedProject();
  if (!project) return;

  state.artifacts = await api(`/projects/${project.id}/artifacts`);
  renderArtifacts();
}

function renderArtifacts() {
  els.artifactCount.textContent = String(state.artifacts.length);
  els.artifactList.innerHTML = "";

  if (state.artifacts.length === 0) {
    els.artifactList.innerHTML = `<p class="item-meta">${escapeHtml(t("noArtifacts"))}</p>`;
    return;
  }

  for (const artifact of state.artifacts) {
    const item = document.createElement("article");
    item.className = "item";
    item.innerHTML = `
      <p class="item-title"></p>
      <p class="item-meta"></p>
      <pre class="item-body"></pre>
    `;
    item.querySelector(".item-title").textContent = artifact.title || artifact.type;
    item.querySelector(".item-meta").textContent =
      `${artifact.type} - v${artifact.version} - ${formatDate(artifact.created_at)}`;
    item.querySelector(".item-body").textContent = artifactBodyText(artifact);
    els.artifactList.append(item);
  }
}

function renderDraftPreview() {
  const draft = latestDraft();
  if (!draft) {
    els.draftStatus.textContent = t("noDraft");
    els.draftToc.classList.add("hidden");
    els.draftToc.innerHTML = "";
    els.draftPreview.classList.add("markdown-body");
    els.draftPreview.textContent = t("draftEmpty");
    return;
  }
  els.draftStatus.textContent = `v${draft.version}`;
  const markdown = artifactBodyText(draft);
  els.draftViewToggle.textContent = state.draftView === "rendered" ? t("raw") : t("rendered");
  els.draftPreview.classList.toggle("markdown-body", state.draftView === "rendered");
  if (state.draftView === "rendered") {
    const rendered = renderMarkdown(markdown);
    els.draftPreview.innerHTML = rendered.html;
    els.draftToc.innerHTML = renderToc(rendered.toc);
    els.draftToc.classList.toggle("hidden", rendered.toc.length === 0);
  } else {
    els.draftToc.classList.add("hidden");
    els.draftToc.innerHTML = "";
    els.draftPreview.textContent = markdown;
  }
}

function renderNextAction() {
  const project = selectedProject();
  if (!project) return;

  const pendingCount = state.questions.filter((question) => question.status === "pending").length;
  els.nextAction.className = "next-action";
  els.nextActionItems.innerHTML = "";
  els.nextActionItems.classList.add("hidden");

  if (pendingCount > 0) {
    els.nextAction.classList.add("needs-answer");
    els.nextActionTitle.textContent =
      state.language === "ko"
        ? `${pendingCount}개 질문에 답변`
        : `Answer ${pendingCount} question${pendingCount === 1 ? "" : "s"}`;
    els.nextActionBody.textContent = t("writerNeedsInput");
    els.nextActionItems.classList.remove("hidden");
    for (const question of state.questions.filter((item) => item.status === "pending")) {
      const item = document.createElement("form");
      item.className = "quick-question";
      const questionText =
        typeof question.question.question === "string"
          ? question.question.question
          : JSON.stringify(question.question);
      item.innerHTML = `
        <p></p>
        <div class="answer-row">
          <input aria-label="${escapeHtml(t("answer"))}" required placeholder="${escapeHtml(t("answer"))}" />
          <button type="submit">${escapeHtml(t("answer"))}</button>
        </div>
      `;
      item.querySelector("p").textContent = questionText;
      const input = item.querySelector("input");
      input.value = getAnswerDraft(question.id);
      input.addEventListener("input", () => {
        setAnswerDraft(question.id, input.value);
      });
      item.addEventListener("submit", async (event) => {
        event.preventDefault();
        await answerQuestion(question.id, input.value);
      });
      els.nextActionItems.append(item);
    }
    return;
  }

  if (project.status === "completed") {
    els.nextAction.classList.add("complete");
    els.nextActionTitle.textContent = t("reviewDraft");
    els.nextActionBody.textContent = t("reviewDraftBody");
    return;
  }

  if (project.status === "failed") {
    els.nextAction.classList.add("failed");
    els.nextActionTitle.textContent = t("pipelineFailed");
    els.nextActionBody.textContent = t("pipelineFailedBody");
    return;
  }

  if (project.status === "running") {
    els.nextActionTitle.textContent = t("writingInProgress");
    els.nextActionBody.textContent = t("writingInProgressBody");
    return;
  }

  els.nextActionTitle.textContent = t("startWritingAction");
  els.nextActionBody.textContent = t("startWritingActionBody");
}

function renderTabs() {
  for (const button of document.querySelectorAll(".tab-button")) {
    button.classList.toggle("active", button.dataset.tab === state.activeTab);
  }
  for (const pane of document.querySelectorAll(".tab-pane")) {
    pane.classList.add("hidden");
  }
  document.querySelector(`#${state.activeTab}Pane`)?.classList.remove("hidden");
}

function rerenderCurrentView() {
  applyStaticTranslations();
  els.projectCount.textContent =
    state.language === "ko"
      ? `${state.projects.length}개 프로젝트`
      : `${state.projects.length} project${state.projects.length === 1 ? "" : "s"}`;
  if (state.projects.length > 0) {
    renderProjects();
  }
  if (selectedProject()) {
    const project = selectedProject();
    els.detailMeta.textContent =
      `${phaseLabel(project.current_phase)} - ${t("created")} ${formatDate(project.created_at)} - ${t("updated")} ${formatDate(project.updated_at)}`;
    els.detailStatus.textContent = statusLabel(project.status);
  }
  renderProgress();
  renderQuestions();
  renderArtifacts();
  renderDraftPreview();
  renderNextAction();
  renderTabs();
}

function toggleHidden(element) {
  element.classList.toggle("hidden");
}

els.languageSelect?.addEventListener("change", () => {
  state.language = els.languageSelect.value === "ko" ? "ko" : "en";
  localStorage.setItem("docugenLanguage", state.language);
  rerenderCurrentView();
});

els.themeSelect?.addEventListener("change", () => {
  state.theme = els.themeSelect.value === "pastel" ? "pastel" : "simpsons";
  localStorage.setItem("docugenTheme", state.theme);
  applyTheme();
});

els.refreshButton.addEventListener("click", async () => {
  try {
    await loadHealth();
    await loadProjects();
    showToast(t("refreshed"));
  } catch (error) {
    showToast(error.message, true);
  }
});

els.newProjectToggle.addEventListener("click", () => {
  toggleHidden(els.projectForm);
});

els.addQuestionToggle.addEventListener("click", () => {
  toggleHidden(els.questionForm);
});

els.addArtifactToggle.addEventListener("click", () => {
  toggleHidden(els.artifactForm);
});

els.draftViewToggle.addEventListener("click", () => {
  state.draftView = state.draftView === "rendered" ? "raw" : "rendered";
  renderDraftPreview();
});

els.exportButton.addEventListener("click", async () => {
  const project = selectedProject();
  if (!project) return;
  try {
    const result = await api(`/projects/${project.id}/export`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    showToast(t("exportedTo", { path: result.file_path }));
  } catch (error) {
    showToast(error.message, true);
  }
});

async function rerunFromStep(phase) {
  const project = selectedProject();
  if (!project) return;
  const label = phaseLabel(phase);
  if (!window.confirm(t("rerunConfirm", { phase: label }))) {
    return;
  }
  setRunButtonRunning(true);
  resetProgressForRun(phase);
  try {
    const result = await api(`/projects/${project.id}/run`, {
      method: "POST",
      body: JSON.stringify({ force_from: phase }),
    });
    showToast(result.message || t("reranFrom", { phase: label }));
    startRunPolling();
  } catch (error) {
    stopRunPolling();
    setRunButtonRunning(false);
    await loadProgress().catch(() => {});
    throw error;
  }
}

for (const button of document.querySelectorAll(".tab-button")) {
  button.addEventListener("click", () => {
    state.activeTab = button.dataset.tab;
    renderTabs();
  });
}

els.runButton.addEventListener("click", async () => {
  const project = selectedProject();
  if (!project) return;

  setRunButtonRunning(true);
  resetProgressForRun("intake");

  try {
    const result = await api(`/projects/${project.id}/run`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    state.selectedProjectId = result.project.id;
    showToast(result.message || t("writingInProgress"));
    startRunPolling();
  } catch (error) {
    showToast(error.message, true);
    stopRunPolling();
    setRunButtonRunning(false);
    await loadProgress().catch(() => {});
  }
});

els.deleteProjectButton.addEventListener("click", async () => {
  const project = selectedProject();
  if (!project) return;

  const confirmed = window.confirm(
    t("deleteProjectConfirm", { title: project.title }),
  );
  if (!confirmed) return;

  try {
    await api(`/projects/${project.id}`, { method: "DELETE" });
    state.selectedProjectId = null;
    state.questions = [];
    state.artifacts = [];
    state.progress = null;
    showToast(t("projectDeleted"));
    await loadProjects();
  } catch (error) {
    showToast(error.message, true);
  }
});

els.projectForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const project = await api("/projects", {
      method: "POST",
      body: JSON.stringify({
        title: els.projectTitle.value,
        initial_request: els.projectRequest.value,
      }),
    });
    state.selectedProjectId = project.id;
    els.projectForm.reset();
    els.projectForm.classList.add("hidden");
    showToast(t("projectCreated"));
    await loadProjects();
  } catch (error) {
    showToast(error.message, true);
  }
});

els.questionForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const project = selectedProject();
  if (!project) return;

  try {
    await api(`/projects/${project.id}/questions`, {
      method: "POST",
      body: JSON.stringify({
        phase: els.questionPhase.value,
        question: {
          question: els.questionText.value,
        },
      }),
    });
    els.questionText.value = "";
    showToast(t("questionAdded"));
    await loadQuestions();
    renderNextAction();
  } catch (error) {
    showToast(error.message, true);
  }
});

els.questionFilter.addEventListener("change", () => {
  loadQuestions()
    .then(renderNextAction)
    .catch((error) => showToast(error.message, true));
});

els.artifactForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const project = selectedProject();
  if (!project) return;

  try {
    const content = els.artifactContent.value.trim()
      ? JSON.parse(els.artifactContent.value)
      : {};
    await api(`/projects/${project.id}/artifacts`, {
      method: "POST",
      body: JSON.stringify({
        type: els.artifactType.value,
        title: els.artifactTitle.value || null,
        content,
      }),
    });
    els.artifactTitle.value = "";
    els.artifactContent.value = "{}";
    showToast(t("artifactSaved"));
    await loadArtifacts();
    renderDraftPreview();
  } catch (error) {
    showToast(error.message, true);
  }
});

async function boot() {
  if (!translations[state.language]) {
    state.language = "en";
  }
  applyTheme();
  applyStaticTranslations();
  try {
    await loadHealth();
    await loadProjects();
  } catch (error) {
    showToast(error.message, true);
  }
}

boot();
