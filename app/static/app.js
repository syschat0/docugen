const state = {
  projects: [],
  docTypes: [],
  selectedProjectId: new URLSearchParams(window.location.search).get("project")?.trim() || null,
  progressTimer: null,
  activeTab: "questions",
  draftView: "rendered",
  language: localStorage.getItem("docugenLanguage") || "en",
  theme: localStorage.getItem("docugenTheme") || "pastel",
  qualityOpen: localStorage.getItem("docugenQualityPanel") === "open",
  sidebarCollapsed:
    (localStorage.getItem("docugenSidebar") ||
      (window.matchMedia("(max-width: 920px)").matches ? "collapsed" : "open")) ===
    "collapsed",
  questions: [],
  answerDrafts: {},
  artifacts: [],
  references: [],
  projectSettings: null,
  quality: null,
  viewDraftId: null,
  compareSelection: [],
  versionsOpen: false,
  progress: null,
  renderedProjectId: null,
  appliedPhase: null,
  selectedStepPhase: null,
  lastStepDetailKey: null,
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
    answersSaved: "Saved {count} answers.",
    appTitle: "LLM Document Agent",
    artifactSaved: "Artifact saved.",
    artifacts: "Artifacts",
    audience: "Audience",
    changed: "Changed",
    chapters: "Chapters",
    characters: "Characters",
    checkingApi: "Checking API status",
    compare: "Compare",
    compareClose: "Close comparison",
    compareConditions: "Generation condition changes",
    compareNoChanges: "These versions are identical.",
    comparePickSecond: "v{version} selected — pick one more version to compare",
    compareSummary: "{changed} changed · {added} added · {removed} removed",
    compareTitle: "Comparing v{from} → v{to}",
    completed: "completed",
    review_needed: "review needed",
    createProject: "Create Project",
    created: "created",
    contents: "Contents",
    currentProject: "Current Project",
    delete: "Delete",
    details: "Details",
    deleteAnswer: "Delete Answer",
    deleteAnswerConfirm: "Delete this answer and make the question pending again?",
    deleteProject: "Delete project",
    deleteProjectConfirm:
      'Delete "{title}"? This will remove its questions, answers, artifacts, summaries, and run logs.',
    diffAdded: "Added",
    diffChanged: "Changed",
    diffRemoved: "Removed",
    diffUnchanged: "Unchanged sections ({count})",
    draftEmpty: "Run the pipeline to generate a draft.",
    draftPreview: "Draft Preview",
    duration: "Duration",
    editAnswer: "Edit Answer",
    emptyBody: "Choose a project from the sidebar, or create a new one to start the writing pipeline.",
    emptyTitle: "Select or create a project",
    error: "Error",
    export: "Export",
    exportedTo: "Exported to {path}",
    formView: "Form View",
    feedbackApplied: "Applied",
    feedbackPanelTitle: "Comments for section {id}",
    feedbackPending: "Pending",
    feedbackPlaceholder: "Write an improvement comment (multi-line supported)",
    feedbackPrompt: "Improvement comment for section {id}:",
    feedbackSaved: "Comment saved. It will be applied to section {id} on the next run.",
    close: "Close",
    noFeedback: "No comments yet.",
    saveComment: "Save Comment",
    finalMerge: "Final merge",
    goal: "Goal",
    idle: "Idle",
    initialRequest: "Initial request",
    jsonContent: "JSON content",
    language: "Language",
    mode: "Mode",
    new: "New",
    nextAction: "Next Action",
    noAnswersToSave: "Enter at least one answer first.",
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
    engine: "Search engine",
    query: "Query",
    queries: "Queries",
    querySource: "Query source",
    topupSearches: "Section top-up searches",
    question: "Question",
    referenceFiles: "Attachments (.txt, .md)",
    referenceUrls: "Reference URLs (one per line)",
    references: "References",
    referencesFailed: "Some references could not be loaded: {errors}",
    noReferences: "No references.",
    editRequest: "Edit request",
    cancel: "Cancel",
    addUrl: "Add URL",
    addFile: "Add File",
    removeReference: "Remove",
    runConditions: "Run conditions",
    externalSearch: "External search",
    sectionSearch: "Section top-up search",
    searchEngine1: "Search engine (1st)",
    searchEngine2: "Search engine (2nd)",
    searchEngine3: "Search engine (3rd)",
    engineNone: "None",
    searchHeadless: "Headless browser",
    searchStealth: "Stealth mode",
    searchLocale: "Result locale",
    searchQueryLanguage: "Query language",
    queryLangNative: "Request language",
    queryLangEnglish: "English",
    queryLangBoth: "Mixed (KR + EN)",
    docType: "Document type",
    autoDetect: "Auto detect",
    docTypeSaved: "Document type saved. The next run will rewrite the document.",
    styleSamples: "Style samples",
    styleSamplesHint: "Upload your own writing (.txt, .md); the document will imitate its voice.",
    noStyleSamples: "No style samples.",
    targetLength: "Target length (characters)",
    targetLengthAuto: "Auto (from the request)",
    citationStyle: "Citation style",
    citationNumeric: "Numbered [1]",
    citationAuthorDate: "Author-date (APA)",
    useDefault: "Use default",
    on: "On",
    off: "Off",
    requestUpdated: "Request updated. It will be applied on the next run.",
    referenceAdded: "Reference added. It will be applied on the next run.",
    referenceRemoved: "Reference removed. It will be applied on the next run.",
    settingsSaved: "Run conditions saved. They will be applied on the next run.",
    enterUrl: "Enter a URL first.",
    selectFiles: "Choose at least one file.",
    versions: "Versions",
    versionHistory: "Version history",
    viewVersion: "View",
    restoreVersion: "Restore",
    restoredToast: "Restored as a new version.",
    latestBadge: "Latest",
    restoredFrom: "restored from v{version}",
    condSearch: "Search",
    condCitations: "Citations",
    condRefs: "Refs",
    condModel: "Model",
    condLength: "Target length",
    condDocType: "Document type",
    noVersions: "No versions yet.",
    questionAdded: "Question added.",
    questions: "Questions",
    raw: "Raw",
    ready: "Ready",
    readyBody: "Start the writing pipeline when you are ready.",
    refresh: "Refresh",
    refreshed: "Refreshed.",
    releaseNotes: "Features & Releases",
    llmSettings: "LLM Settings",
    llmSettingsTitle: "LLM Provider",
    llmSettingsSub: "Choose which model backend the writing pipeline uses.",
    provider: "Provider",
    baseUrl: "Base URL",
    apiKey: "API Key",
    model: "Model",
    testConnection: "Test connection",
    save: "Save",
    llmSaved: "LLM provider saved.",
    llmTesting: "Testing connection…",
    llmTestOk: "Connected. Model: {model}",
    llmTestFail: "Failed: {error}",
    imageSettingsTitle: "Image generation",
    imageSettingsSub: "Generate a cover image and per-section illustrations.",
    imageSaved: "Image provider saved.",
    imageMainToggle: "Cover image below the document title",
    imageSectionToggle: "Section images in the body",
    imageMaxCount: "Max body images",
    imageStyleLabel: "Image style",
    imageStylePhoto: "Photo (realistic)",
    imageStyleIllustration: "Flat illustration",
    rendered: "Rendered",
    reranFrom: "Reran from {phase}.",
    rerunConfirm: "Rerun from {phase}? Downstream artifacts will be regenerated.",
    rerunFromHere: "Rerun from here",
    reviewDraft: "Review the draft",
    reviewDraftBody: "The staged pipeline completed. Review the draft preview or inspect intermediate artifacts.",
    qualitySummary: "Quality Summary",
    qualityReady: "Ready",
    qualityReviewNeeded: "Review needed",
    strongSources: "Strong sources",
    lowQualitySources: "Low-quality sources",
    citedParagraphs: "Cited paragraphs",
    verifiedEvidence: "Verified citations",
    reviewIssues: "Review findings",
    writingIssues: "Writing flags",
    structureIssues: "Readability flags",
    improveDraft: "Improve Draft",
    regenerateDraft: "Regenerate Draft",
    qualityWarning_low_quality_sources: "Some claims rely on wiki, blog, community, or unidentified sources.",
    qualityWarning_high_stakes_without_strong_sources: "This high-stakes topic has no government, academic, or institutional source.",
    qualityWarning_review_findings: "The reviewers found issues that should be checked after automatic revision.",
    qualityWarning_review_incomplete: "One or more automatic quality reviews did not complete.",
    qualityWarning_no_cited_paragraphs: "No eligible body paragraph contains a citation.",
    qualityWarning_unverified_evidence: "Some cited claims do not have a valid excerpt in the evidence ledger.",
    qualityWarning_stale_evidence: "Some evidence ledgers are missing or stale after section revision.",
    qualityWarning_stale_due_inputs: "The displayed draft predates the latest input or partial run.",
    qualityWarning_duplicate_content: "Potentially repeated sentences were found across the draft.",
    qualityWarning_possible_contradictions: "Highly similar statements with opposing polarity were found.",
    qualityWarning_unsupported_overclaims: "This high-stakes draft contains absolute claims without inline evidence.",
    qualityWarning_long_sentences: "Some sentences are long enough to reduce readability.",
    qualityWarning_long_paragraphs: "Some paragraphs are too dense for the selected document type.",
    qualityWarning_list_heavy_sections: "Some sections rely on lists for most of their content.",
    qualityWarning_heading_structure: "One or more sections have a missing or additional Markdown heading.",
    qualityWarning_missing_introduction: "This long-form document has no identifiable introduction or context section.",
    qualityWarning_missing_conclusion: "This long-form document has no identifiable conclusion, summary, or recommendations section.",
    writingIssue_duplicate: "Possible repetition ({sections}): {excerpt}",
    writingIssue_possible_contradiction: "Possible contradiction ({sections}): {excerpt}",
    writingIssue_unsupported_overclaim: "Unsupported absolute claim ({sections}): {excerpt}",
    writingRepairSummary: "Automatic sentence repair improved {repaired} of {attempted} targeted sections.",
    qualityReviewTarget: "Review target section {sections}",
    qualityReviewTargetDetail: "Review target section {sections}: {excerpt}",
    jumpToQualityIssue: "Jump to section {id}",
    qualityIssueNotFound: "The target section could not be located in the latest draft.",
    acknowledgeIssue: "Reviewed",
    waiveIssue: "Allow exception",
    clearIssueDecision: "Undo",
    issueDecisionReason: "Record why this issue was reviewed or should be treated as an exception:",
    issueAcknowledged: "Reviewed: {reason}",
    issueWaived: "Exception: {reason}",
    issueDecisionSaved: "Quality issue decision saved.",
    issueDecisionCleared: "Quality issue decision removed.",
    requestIssueFix: "Request fix",
    qualityFeedbackTemplate: "Please fix this quality issue.\n- Issue: {issue}\n- Problem excerpt: {excerpt}\n- Related sections: {sections}",
    issueName_duplicate: "Possible repetition",
    issueName_possible_contradiction: "Possible contradiction",
    issueName_unsupported_overclaim: "Unsupported absolute claim",
    issueName_long_sentence: "Long sentence",
    issueName_long_paragraph: "Dense paragraph",
    issueName_list_heavy: "List-heavy section",
    issueName_heading_structure: "Heading structure",
    issueName_missing_introduction: "Introduction not identified",
    issueName_missing_conclusion: "Conclusion not identified",
    issueName_review_target: "Reviewer-flagged issue",
    issueHelp_duplicate: "Nearly identical sentences appear in more than one place. Consider merging or trimming one side.",
    issueHelp_possible_contradiction: "Two sentences read as opposite claims about the same topic. Check whether they actually conflict.",
    issueHelp_unsupported_overclaim: "An absolute claim (always, never, the only) has no citation. Add evidence or soften the wording.",
    issueHelp_long_sentence: "One sentence exceeds the length guideline for this document type. Splitting it into two or three makes it easier to read.",
    issueHelp_long_paragraph: "One paragraph is long and packed with sentences, leaving no resting point. Split it by topic.",
    issueHelp_list_heavy: "Most of this section is bullet lists. Keep only the key items as a list and turn the rest into prose.",
    issueHelp_heading_structure: "This section does not have exactly one heading. Tidy the heading hierarchy.",
    issueHelp_missing_introduction: "No opening section reads as an introduction. Consider adding or renaming one.",
    issueHelp_missing_conclusion: "No closing section reads as a conclusion. Consider adding or renaming one.",
    issueHelp_review_target: "The AI reviewer recommended rewriting these sections. Running Improve Draft revises them first.",
    saveAndImproveSection: "Save & improve section",
    sectionImprovementStarted: "Feedback saved. Improving section {id} now.",
    structureIssue_long_sentence: "Long sentence ({sections}): {excerpt}",
    structureIssue_long_paragraph: "Dense paragraph ({sections}): {excerpt}",
    structureIssue_list_heavy: "List-heavy section ({sections}): {excerpt}",
    structureIssue_heading_structure: "Heading structure ({sections}): {excerpt}",
    structureIssue_missing_introduction: "Introduction not identified near {sections}: {excerpt}",
    structureIssue_missing_conclusion: "Conclusion not identified near {sections}: {excerpt}",
    saveAllAnswers: "Save All Answers",
    saveAnswersAndRun: "Save & Start Writing",
    saveArtifact: "Save Artifact",
    searchError: "Search error",
    sections: "Sections",
    sectionDrafts: "Section drafts",
    sourceSummaries: "Source summaries",
    sources: "Sources",
    noSourcesFound: "No sources found",
    noSourcesUsed: "Written without sources",
    usedSources: "Sources used",
    fromChapterResearch: "chapter research",
    chapterDigests: "Chapter digests",
    glossary: "Glossary",
    smoothedSeams: "Smoothed transitions",
    started: "started",
    startWriting: "Start Writing",
    startWritingAction: "Start writing",
    startWritingActionBody: "Run the staged pipeline to ask intake questions or generate section-level drafts.",
    summaries: "Summaries",
    theme: "Theme",
    themePastel: "Pastel Watercolor",
    themeSimpsons: "Simpsons",
    themeNewspaper: "New York Times",
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
    cancelWriting: "Cancel writing",
    cancelling: "Cancelling…",
    cancelRequested: "Cancellation requested. The run will stop at the next step.",
    cancelled: "Cancelled",
    runCancelled: "Writing cancelled",
    runCancelledBody: "The run was cancelled. Start writing again to resume from the last completed step.",
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
    answersSaved: "답변 {count}개를 저장했습니다.",
    appTitle: "LLM 문서 작성 에이전트",
    artifactSaved: "산출물을 저장했습니다.",
    artifacts: "산출물",
    audience: "대상 독자",
    changed: "변경 여부",
    chapters: "목차",
    characters: "문자 수",
    checkingApi: "API 상태 확인 중",
    compare: "비교",
    compareClose: "비교 닫기",
    compareConditions: "생성 조건 변경",
    compareNoChanges: "두 버전의 내용이 동일합니다.",
    comparePickSecond: "v{version} 선택됨 — 비교할 버전을 하나 더 선택하세요",
    compareSummary: "변경 {changed} · 추가 {added} · 삭제 {removed}",
    compareTitle: "v{from} → v{to} 비교",
    completed: "완료",
    review_needed: "검토 필요",
    createProject: "프로젝트 생성",
    created: "생성",
    contents: "목차",
    currentProject: "현재 프로젝트",
    delete: "삭제",
    details: "상세",
    deleteAnswer: "답변 삭제",
    deleteAnswerConfirm: "이 답변을 삭제하고 질문을 다시 대기 상태로 바꿀까요?",
    deleteProject: "프로젝트 삭제",
    deleteProjectConfirm:
      '"{title}" 프로젝트를 삭제할까요? 질문, 답변, 산출물, 요약, 실행 로그가 모두 삭제됩니다.',
    diffAdded: "추가됨",
    diffChanged: "변경됨",
    diffRemoved: "삭제됨",
    diffUnchanged: "변경 없는 섹션 ({count})",
    draftEmpty: "파이프라인을 실행하면 초안이 생성됩니다.",
    draftPreview: "초안 미리보기",
    qualitySummary: "품질 요약",
    qualityReady: "준비됨",
    qualityReviewNeeded: "검토 필요",
    strongSources: "신뢰 출처",
    lowQualitySources: "저신뢰 출처",
    citedParagraphs: "인용 문단",
    verifiedEvidence: "검증된 인용",
    reviewIssues: "검토 이슈",
    writingIssues: "문장 품질 이슈",
    structureIssues: "구조·가독성 이슈",
    improveDraft: "문서 개선",
    regenerateDraft: "초안 다시 생성",
    qualityWarning_low_quality_sources: "일부 주장이 위키·블로그·커뮤니티 또는 식별되지 않은 출처에 의존합니다.",
    qualityWarning_high_stakes_without_strong_sources: "고위험 주제이지만 정부·학술·기관 출처가 없습니다.",
    qualityWarning_review_findings: "자동 수정 후 다시 확인해야 할 검토 이슈가 있습니다.",
    qualityWarning_review_incomplete: "일부 자동 품질 검토가 완료되지 않았습니다.",
    qualityWarning_no_cited_paragraphs: "인용 가능한 본문 문단에 인용이 없습니다.",
    qualityWarning_unverified_evidence: "일부 인용 주장에 출처 원문과 일치하는 근거가 없습니다.",
    qualityWarning_stale_evidence: "섹션 수정 후 인용 근거 기록이 없거나 오래된 상태입니다.",
    qualityWarning_stale_due_inputs: "표시된 초안은 최신 입력 또는 부분 실행보다 이전 버전입니다.",
    qualityWarning_duplicate_content: "초안에서 반복 가능성이 높은 문장을 발견했습니다.",
    qualityWarning_possible_contradictions: "표현은 유사하지만 긍정·부정 방향이 상반된 문장을 발견했습니다.",
    qualityWarning_unsupported_overclaims: "고위험 문서에 인용 근거 없는 단정 표현이 있습니다.",
    qualityWarning_long_sentences: "읽기 어려울 정도로 긴 문장이 있습니다.",
    qualityWarning_long_paragraphs: "선택한 문서 유형에 비해 지나치게 조밀한 문단이 있습니다.",
    qualityWarning_list_heavy_sections: "내용 대부분을 목록에 의존하는 섹션이 있습니다.",
    qualityWarning_heading_structure: "제목이 없거나 제목이 추가된 섹션이 있습니다.",
    qualityWarning_missing_introduction: "장문 문서의 도입·배경 섹션을 식별할 수 없습니다.",
    qualityWarning_missing_conclusion: "장문 문서의 결론·요약·제언 섹션을 식별할 수 없습니다.",
    writingIssue_duplicate: "반복 가능성 ({sections}): {excerpt}",
    writingIssue_possible_contradiction: "상반된 진술 가능성 ({sections}): {excerpt}",
    writingIssue_unsupported_overclaim: "근거 없는 단정 ({sections}): {excerpt}",
    writingRepairSummary: "문장 자동 보정 대상 {attempted}개 중 {repaired}개 섹션을 개선했습니다.",
    qualityReviewTarget: "검토 대상 섹션 {sections}",
    qualityReviewTargetDetail: "검토 대상 섹션 {sections}: {excerpt}",
    jumpToQualityIssue: "섹션 {id}로 이동",
    qualityIssueNotFound: "최신 초안에서 대상 섹션을 찾을 수 없습니다.",
    acknowledgeIssue: "확인 완료",
    waiveIssue: "예외 처리",
    clearIssueDecision: "해제",
    issueDecisionReason: "이 이슈를 확인했거나 예외로 처리하는 이유를 기록하세요:",
    issueAcknowledged: "확인 완료: {reason}",
    issueWaived: "예외 처리: {reason}",
    issueDecisionSaved: "품질 이슈 처리를 저장했습니다.",
    issueDecisionCleared: "품질 이슈 처리를 해제했습니다.",
    requestIssueFix: "수정 요청",
    qualityFeedbackTemplate: "다음 품질 이슈를 수정해 주세요.\n- 이슈 내용: {issue}\n- 문제 문장: {excerpt}\n- 관련 섹션: {sections}",
    issueName_duplicate: "반복 가능성",
    issueName_possible_contradiction: "상반된 진술 가능성",
    issueName_unsupported_overclaim: "근거 없는 단정",
    issueName_long_sentence: "긴 문장",
    issueName_long_paragraph: "조밀한 문단",
    issueName_list_heavy: "목록 편중",
    issueName_heading_structure: "제목 구조",
    issueName_missing_introduction: "도입부 확인 필요",
    issueName_missing_conclusion: "결론부 확인 필요",
    issueName_review_target: "검토 지적 사항",
    issueHelp_duplicate: "거의 같은 문장이 두 곳 이상에서 반복됩니다. 한쪽을 줄이거나 합치는 것을 검토하세요.",
    issueHelp_possible_contradiction: "같은 주제를 반대로 서술한 것처럼 읽히는 두 문장이 있습니다. 실제 모순인지 확인해 주세요.",
    issueHelp_unsupported_overclaim: "'항상·절대·유일' 같은 단정 표현에 인용 근거가 없습니다. 근거를 붙이거나 표현을 완화하세요.",
    issueHelp_long_sentence: "한 문장이 문서 유형별 기준 길이를 넘습니다. 두세 문장으로 나누면 읽기 쉬워집니다.",
    issueHelp_long_paragraph: "한 문단이 길고 문장이 많아 쉬어갈 지점이 없습니다. 주제 단위로 문단을 나눠 보세요.",
    issueHelp_list_heavy: "섹션 대부분이 목록으로 구성되어 있습니다. 핵심만 목록으로 남기고 나머지는 문장으로 풀어 보세요.",
    issueHelp_heading_structure: "섹션의 제목 개수가 기준(1개)과 다릅니다. 제목 계층을 정리해 주세요.",
    issueHelp_missing_introduction: "문서 앞부분에서 도입부 성격의 섹션을 찾지 못했습니다. 도입 섹션을 추가하거나 제목을 조정해 보세요.",
    issueHelp_missing_conclusion: "문서 끝부분에서 결론 성격의 섹션을 찾지 못했습니다. 마무리 섹션을 추가하거나 제목을 조정해 보세요.",
    issueHelp_review_target: "AI 검토자가 다시 쓰기를 권장한 섹션입니다. '문서 개선'을 실행하면 우선적으로 수정됩니다.",
    saveAndImproveSection: "저장 후 섹션 개선",
    sectionImprovementStarted: "피드백을 저장했습니다. 섹션 {id} 개선을 시작합니다.",
    structureIssue_long_sentence: "긴 문장 ({sections}): {excerpt}",
    structureIssue_long_paragraph: "조밀한 문단 ({sections}): {excerpt}",
    structureIssue_list_heavy: "목록 편중 ({sections}): {excerpt}",
    structureIssue_heading_structure: "제목 구조 ({sections}): {excerpt}",
    structureIssue_missing_introduction: "도입부 확인 필요 ({sections}): {excerpt}",
    structureIssue_missing_conclusion: "결론부 확인 필요 ({sections}): {excerpt}",
    duration: "소요 시간",
    editAnswer: "답변 수정",
    emptyBody: "왼쪽에서 프로젝트를 선택하거나 새 프로젝트를 만들어 작성 파이프라인을 시작하세요.",
    emptyTitle: "프로젝트를 선택하거나 생성하세요",
    error: "오류",
    export: "내보내기",
    exportedTo: "{path}로 내보냈습니다.",
    formView: "양식 보기",
    feedbackApplied: "반영됨",
    feedbackPanelTitle: "섹션 {id} 코멘트",
    feedbackPending: "대기 중",
    feedbackPlaceholder: "개선 코멘트를 입력하세요 (여러 줄 가능)",
    feedbackPrompt: "섹션 {id}에 대한 개선 코멘트를 입력하세요:",
    feedbackSaved: "코멘트를 저장했습니다. 다음 실행 시 섹션 {id}에 반영됩니다.",
    close: "닫기",
    noFeedback: "아직 코멘트가 없습니다.",
    saveComment: "코멘트 저장",
    finalMerge: "최종 병합",
    goal: "목표",
    idle: "대기",
    initialRequest: "초기 요청",
    jsonContent: "JSON 내용",
    language: "언어",
    mode: "모드",
    new: "새로 만들기",
    nextAction: "다음 작업",
    noAnswersToSave: "먼저 답변을 입력하세요.",
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
    engine: "검색 엔진",
    query: "검색어",
    queries: "검색어 목록",
    querySource: "검색어 출처",
    topupSearches: "섹션 보강 검색",
    question: "질문",
    referenceFiles: "첨부 파일 (.txt, .md)",
    referenceUrls: "참고 URL (한 줄에 하나)",
    references: "참고 자료",
    referencesFailed: "일부 참고 자료를 불러오지 못했습니다: {errors}",
    noReferences: "참고 자료가 없습니다.",
    editRequest: "요청 편집",
    cancel: "취소",
    addUrl: "URL 추가",
    addFile: "파일 추가",
    removeReference: "삭제",
    runConditions: "생성 조건",
    externalSearch: "외부 검색",
    sectionSearch: "섹션 보강 검색",
    searchEngine1: "검색 엔진 (1순위)",
    searchEngine2: "검색 엔진 (2순위)",
    searchEngine3: "검색 엔진 (3순위)",
    engineNone: "없음",
    searchHeadless: "헤드리스 브라우저",
    searchStealth: "스텔스 모드",
    searchLocale: "결과 로케일",
    searchQueryLanguage: "검색어 언어",
    queryLangNative: "요청 언어",
    queryLangEnglish: "영어",
    queryLangBoth: "혼합 (한+영)",
    docType: "문서 유형",
    autoDetect: "자동 감지",
    docTypeSaved: "문서 유형을 저장했습니다. 다음 실행 시 문서를 새로 작성합니다.",
    styleSamples: "문체 샘플",
    styleSamplesHint: "직접 쓴 글(.txt, .md)을 올리면 그 문체를 모사해 작성합니다.",
    noStyleSamples: "문체 샘플이 없습니다.",
    targetLength: "목표 분량(자)",
    targetLengthAuto: "자동 (요청문에서 추출)",
    citationStyle: "참고문헌 표기법",
    citationNumeric: "번호식 [1]",
    citationAuthorDate: "저자-연도식 (APA)",
    useDefault: "기본값 사용",
    on: "켜기",
    off: "끄기",
    requestUpdated: "요청을 수정했습니다. 다음 실행 시 반영됩니다.",
    referenceAdded: "참고 자료를 추가했습니다. 다음 실행 시 반영됩니다.",
    referenceRemoved: "참고 자료를 삭제했습니다. 다음 실행 시 반영됩니다.",
    settingsSaved: "생성 조건을 저장했습니다. 다음 실행 시 반영됩니다.",
    enterUrl: "URL을 입력하세요.",
    selectFiles: "파일을 하나 이상 선택하세요.",
    versions: "버전",
    versionHistory: "버전 이력",
    viewVersion: "보기",
    restoreVersion: "복원",
    restoredToast: "새 버전으로 복원했습니다.",
    latestBadge: "최신",
    restoredFrom: "v{version}에서 복원",
    condSearch: "검색",
    condCitations: "인용",
    condRefs: "참조",
    condModel: "모델",
    condLength: "목표 분량",
    condDocType: "문서 유형",
    noVersions: "아직 버전이 없습니다.",
    questionAdded: "질문을 추가했습니다.",
    questions: "질문",
    raw: "원문",
    ready: "준비됨",
    readyBody: "준비되면 작성 파이프라인을 시작하세요.",
    refresh: "새로고침",
    refreshed: "새로고침했습니다.",
    releaseNotes: "기능 및 릴리즈",
    llmSettings: "LLM 설정",
    llmSettingsTitle: "LLM 프로바이더",
    llmSettingsSub: "문서 작성 파이프라인이 사용할 모델 백엔드를 선택하세요.",
    provider: "프로바이더",
    baseUrl: "Base URL",
    apiKey: "API 키",
    model: "모델",
    testConnection: "연결 테스트",
    save: "저장",
    llmSaved: "LLM 프로바이더를 저장했습니다.",
    llmTesting: "연결 테스트 중…",
    llmTestOk: "연결 성공. 모델: {model}",
    llmTestFail: "실패: {error}",
    imageSettingsTitle: "이미지 생성",
    imageSettingsSub: "메인(커버) 이미지와 섹션별 본문 이미지를 생성해 문서에 삽입합니다.",
    imageSaved: "이미지 프로바이더를 저장했습니다.",
    imageMainToggle: "문서 제목 아래 메인(커버) 이미지",
    imageSectionToggle: "본문 섹션 이미지",
    imageMaxCount: "본문 이미지 최대 매수",
    imageStyleLabel: "이미지 스타일",
    imageStylePhoto: "사진(실사)",
    imageStyleIllustration: "플랫 일러스트",
    rendered: "서식 보기",
    reranFrom: "{phase} 단계부터 다시 실행했습니다.",
    rerunConfirm: "{phase} 단계부터 다시 실행할까요? 이후 산출물은 다시 생성됩니다.",
    rerunFromHere: "여기서부터 재실행",
    reviewDraft: "초안 검토",
    reviewDraftBody: "단계별 파이프라인이 완료되었습니다. 초안 미리보기나 중간 산출물을 검토하세요.",
    saveAllAnswers: "답변 모두 저장",
    saveAnswersAndRun: "저장 후 작성 시작",
    saveArtifact: "산출물 저장",
    searchError: "검색 오류",
    sections: "섹션",
    sectionDrafts: "섹션 초안",
    sourceSummaries: "출처 요약",
    sources: "출처",
    noSourcesFound: "검색된 출처가 없습니다.",
    noSourcesUsed: "출처 없이 작성됨",
    usedSources: "사용한 출처",
    fromChapterResearch: "챕터 조사",
    chapterDigests: "챕터 다이제스트",
    glossary: "용어집",
    smoothedSeams: "다듬은 전환부",
    started: "시작",
    startWriting: "작성 시작",
    startWritingAction: "작성 시작",
    startWritingActionBody: "질문을 생성하거나 섹션 단위 초안을 만들기 위해 단계별 파이프라인을 실행하세요.",
    summaries: "요약",
    theme: "테마",
    themePastel: "파스텔 수채화",
    themeSimpsons: "심슨 만화",
    themeNewspaper: "뉴욕타임즈",
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
    cancelWriting: "작성 취소",
    cancelling: "취소 중…",
    cancelRequested: "취소를 요청했습니다. 다음 단계에서 중단됩니다.",
    cancelled: "취소됨",
    runCancelled: "작성이 취소됨",
    runCancelledBody: "실행이 취소되었습니다. 다시 작성 시작을 누르면 마지막 완료 단계부터 이어집니다.",
  },
};

const phaseLabels = {
  en: {
    intake: "Intake questions",
    style_card: "Style card",
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
    feedback_revision: "Feedback revision",
    continuity_review: "Continuity review",
    rubric_review: "Rubric review",
    targeted_revision: "Targeted revision",
    final_merge: "Final merge",
  },
  ko: {
    intake: "질문 수집",
    style_card: "문체 카드",
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
    feedback_revision: "피드백 반영",
    continuity_review: "흐름 검토",
    rubric_review: "품질 평가",
    targeted_revision: "부분 수정",
    final_merge: "최종 병합",
  },
};

const workflowPhases = Object.keys(phaseLabels.en);

const els = {
  appShell: document.querySelector(".app-shell"),
  sidebarToggle: document.querySelector("#sidebarToggle"),
  sidebarBackdrop: document.querySelector("#sidebarBackdrop"),
  healthText: document.querySelector("#healthText"),
  refreshButton: document.querySelector("#refreshButton"),
  runButton: document.querySelector("#runButton"),
  cancelButton: document.querySelector("#cancelButton"),
  deleteProjectButton: document.querySelector("#deleteProjectButton"),
  newProjectToggle: document.querySelector("#newProjectToggle"),
  projectForm: document.querySelector("#projectForm"),
  projectTitle: document.querySelector("#projectTitle"),
  projectRequest: document.querySelector("#projectRequest"),
  projectReferenceUrls: document.querySelector("#projectReferenceUrls"),
  projectReferenceFiles: document.querySelector("#projectReferenceFiles"),
  requestDetails: document.querySelector("#requestDetails"),
  requestSummaryPreview: document.querySelector("#requestSummaryPreview"),
  detailRequest: document.querySelector("#detailRequest"),
  requestView: document.querySelector("#requestView"),
  requestEditForm: document.querySelector("#requestEditForm"),
  editProjectTitle: document.querySelector("#editProjectTitle"),
  editProjectRequest: document.querySelector("#editProjectRequest"),
  editRequestButton: document.querySelector("#editRequestButton"),
  cancelRequestEdit: document.querySelector("#cancelRequestEdit"),
  addReferenceUrl: document.querySelector("#addReferenceUrl"),
  addReferenceUrlButton: document.querySelector("#addReferenceUrlButton"),
  addReferenceFiles: document.querySelector("#addReferenceFiles"),
  addReferenceFilesButton: document.querySelector("#addReferenceFilesButton"),
  searchEnabledSelect: document.querySelector("#searchEnabledSelect"),
  sectionSearchSelect: document.querySelector("#sectionSearchSelect"),
  searchEngine1Select: document.querySelector("#searchEngine1Select"),
  searchEngine2Select: document.querySelector("#searchEngine2Select"),
  searchEngine3Select: document.querySelector("#searchEngine3Select"),
  searchHeadlessSelect: document.querySelector("#searchHeadlessSelect"),
  searchStealthSelect: document.querySelector("#searchStealthSelect"),
  searchLocaleSelect: document.querySelector("#searchLocaleSelect"),
  searchQueryLanguageSelect: document.querySelector("#searchQueryLanguageSelect"),
  citationStyleSelect: document.querySelector("#citationStyleSelect"),
  targetLengthInput: document.querySelector("#targetLengthInput"),
  projectDocType: document.querySelector("#projectDocType"),
  docTypeSelect: document.querySelector("#docTypeSelect"),
  addStyleFiles: document.querySelector("#addStyleFiles"),
  addStyleFilesButton: document.querySelector("#addStyleFilesButton"),
  styleSampleList: document.querySelector("#styleSampleList"),
  referenceList: document.querySelector("#referenceList"),
  projectList: document.querySelector("#projectList"),
  projectCount: document.querySelector("#projectCount"),
  emptyState: document.querySelector("#emptyState"),
  projectDetail: document.querySelector("#projectDetail"),
  detailTitle: document.querySelector("#detailTitle"),
  detailMeta: document.querySelector("#detailMeta"),
  detailStatus: document.querySelector("#detailStatus"),
  statusStrip: document.querySelector("#statusStrip"),
  stripMessage: document.querySelector("#stripMessage"),
  stripProgress: document.querySelector("#stripProgress"),
  stripFill: document.querySelector("#stripFill"),
  stripPercent: document.querySelector("#stripPercent"),
  pipelinePanel: document.querySelector("#pipelinePanel"),
  pipelineSummaryText: document.querySelector("#pipelineSummaryText"),
  qualityPanel: document.querySelector("#qualityPanel"),
  qualityToggle: document.querySelector("#qualityToggle"),
  qualityClose: document.querySelector("#qualityClose"),
  qualityStatus: document.querySelector("#qualityStatus"),
  qualityStrongSources: document.querySelector("#qualityStrongSources"),
  qualityLowSources: document.querySelector("#qualityLowSources"),
  qualityCitationCoverage: document.querySelector("#qualityCitationCoverage"),
  qualityEvidenceCoverage: document.querySelector("#qualityEvidenceCoverage"),
  qualityIssueCount: document.querySelector("#qualityIssueCount"),
  qualityWritingIssueCount: document.querySelector("#qualityWritingIssueCount"),
  qualityStructureIssueCount: document.querySelector("#qualityStructureIssueCount"),
  qualityWarnings: document.querySelector("#qualityWarnings"),
  nextAction: document.querySelector("#nextAction"),
  nextActionTitle: document.querySelector("#nextActionTitle"),
  nextActionBody: document.querySelector("#nextActionBody"),
  nextActionItems: document.querySelector("#nextActionItems"),
  progressPercent: document.querySelector("#progressPercent"),
  progressFill: document.querySelector("#progressFill"),
  progressSteps: document.querySelector("#progressSteps"),
  stepDetail: document.querySelector("#stepDetail"),
  draftStatus: document.querySelector("#draftStatus"),
  versionsButton: document.querySelector("#versionsButton"),
  versionList: document.querySelector("#versionList"),
  draftViewer: document.querySelector("#draftViewer"),
  draftToc: document.querySelector("#draftToc"),
  draftPreview: document.querySelector("#draftPreview"),
  formViewButton: document.querySelector("#formViewButton"),
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
  llmSettingsButton: document.querySelector("#llmSettingsButton"),
  llmSettingsModal: document.querySelector("#llmSettingsModal"),
  llmSettingsClose: document.querySelector("#llmSettingsClose"),
  llmProvider: document.querySelector("#llmProvider"),
  llmBaseUrlRow: document.querySelector("#llmBaseUrlRow"),
  llmBaseUrl: document.querySelector("#llmBaseUrl"),
  llmApiKeyRow: document.querySelector("#llmApiKeyRow"),
  llmApiKey: document.querySelector("#llmApiKey"),
  llmModelRow: document.querySelector("#llmModelRow"),
  llmModel: document.querySelector("#llmModel"),
  llmProviderNote: document.querySelector("#llmProviderNote"),
  llmTestResult: document.querySelector("#llmTestResult"),
  llmTestButton: document.querySelector("#llmTestButton"),
  llmSaveButton: document.querySelector("#llmSaveButton"),
  imageProvider: document.querySelector("#imageProvider"),
  imageBaseUrlRow: document.querySelector("#imageBaseUrlRow"),
  imageBaseUrl: document.querySelector("#imageBaseUrl"),
  imageApiKeyRow: document.querySelector("#imageApiKeyRow"),
  imageApiKey: document.querySelector("#imageApiKey"),
  imageModelRow: document.querySelector("#imageModelRow"),
  imageModel: document.querySelector("#imageModel"),
  imageOptionsRows: document.querySelector("#imageOptionsRows"),
  imageMainToggle: document.querySelector("#imageMainToggle"),
  imageSectionToggle: document.querySelector("#imageSectionToggle"),
  imageMaxCount: document.querySelector("#imageMaxCount"),
  imageStyle: document.querySelector("#imageStyle"),
  imageProviderNote: document.querySelector("#imageProviderNote"),
  imageTestResult: document.querySelector("#imageTestResult"),
  imageTestButton: document.querySelector("#imageTestButton"),
  imageSaveButton: document.querySelector("#imageSaveButton"),
};

const llmSettingsState = { providers: [], active: null, loaded: false };
const imageSettingsState = { providers: [], active: null, options: null, loaded: false };

function applyTheme() {
  document.documentElement.dataset.theme = state.theme;
  if (els.themeSelect) {
    els.themeSelect.value = state.theme;
  }
}

function isNarrowViewport() {
  return window.matchMedia("(max-width: 920px)").matches;
}

function applySidebar() {
  els.appShell?.classList.toggle("sidebar-collapsed", state.sidebarCollapsed);
  els.sidebarToggle?.setAttribute("aria-expanded", String(!state.sidebarCollapsed));
}

function setSidebarCollapsed(collapsed, { persist = true } = {}) {
  state.sidebarCollapsed = collapsed;
  if (persist) {
    localStorage.setItem("docugenSidebar", collapsed ? "collapsed" : "open");
  }
  applySidebar();
}

function toggleSidebar() {
  setSidebarCollapsed(!state.sidebarCollapsed);
}

// On narrow screens the sidebar is an overlay drawer, so close it after the
// user picks a project to reveal the workspace underneath.
function closeSidebarOnNarrow() {
  if (isNarrowViewport() && !state.sidebarCollapsed) {
    setSidebarCollapsed(true, { persist: false });
  }
}

function projectIdFromUrl() {
  return new URLSearchParams(window.location.search).get("project")?.trim() || null;
}

function syncProjectInUrl(projectId) {
  const url = new URL(window.location.href);
  if (projectId) {
    url.searchParams.set("project", projectId);
  } else {
    url.searchParams.delete("project");
  }
  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next !== current) {
    window.history.replaceState(null, "", next);
  }
}

function formViewUrl(projectId) {
  return `/view?project=${encodeURIComponent(projectId)}`;
}

function updateDocumentTitle() {
  const project = selectedProject();
  const base = t("appTitle");
  document.title = project?.title ? `${project.title} · ${base}` : base;
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
  els.qualityClose?.setAttribute("aria-label", t("close"));
  els.themeSelect?.setAttribute("aria-label", t("theme"));
  els.questionFilter?.setAttribute("aria-label", t("questions"));
  if (els.themeSelect) {
    els.themeSelect.value = state.theme;
  }
}

async function api(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const response = await fetch(path, {
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
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

// All draft versions, newest first (list_artifacts already orders by created_at
// DESC, and each rerun appends a higher version instead of overwriting).
function draftVersions() {
  return state.artifacts.filter((artifact) => artifact.type === "draft");
}

function currentDraft() {
  const drafts = draftVersions();
  if (state.viewDraftId) {
    const viewed = drafts.find((draft) => draft.id === state.viewDraftId);
    if (viewed) return viewed;
  }
  return drafts[0] || null;
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

  const urlProjectId = projectIdFromUrl();
  if (urlProjectId && state.projects.some((project) => project.id === urlProjectId)) {
    state.selectedProjectId = urlProjectId;
  } else if (!state.selectedProjectId && state.projects.length > 0) {
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
    const item = document.createElement("div");
    item.className = "project-item";
    item.classList.toggle("active", project.id === state.selectedProjectId);
    item.innerHTML = `
      <button type="button" class="project-select">
        <p class="item-title"></p>
        <p class="item-meta"></p>
      </button>
      <button type="button" class="project-delete" title="${escapeHtml(t("delete"))}" aria-label="${escapeHtml(t("delete"))}">✕</button>
    `;
    item.querySelector(".item-title").textContent = project.title;
    item.querySelector(".item-meta").textContent =
      `${statusLabel(project.status)} - ${phaseLabel(project.current_phase)} - ${formatDate(project.updated_at)}`;
    item.querySelector(".project-select").addEventListener("click", async () => {
      state.selectedProjectId = project.id;
      state.selectedStepPhase = null;
      closeSidebarOnNarrow();
      renderProjects();
      await renderSelectedProject();
    });
    item.querySelector(".project-delete").addEventListener("click", async (event) => {
      event.stopPropagation();
      await deleteProject(project);
    });
    els.projectList.append(item);
  }
}

async function deleteProject(project) {
  const confirmed = window.confirm(
    t("deleteProjectConfirm", { title: project.title }),
  );
  if (!confirmed) return;

  try {
    await api(`/projects/${project.id}`, { method: "DELETE" });
    if (state.selectedProjectId === project.id) {
      state.selectedProjectId = null;
      state.selectedStepPhase = null;
      state.questions = [];
      state.artifacts = [];
      state.progress = null;
      state.quality = null;
    }
    showToast(t("projectDeleted"));
    await loadProjects();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function renderSelectedProject() {
  const project = selectedProject();

  els.emptyState.classList.toggle("hidden", Boolean(project));
  els.projectDetail.classList.toggle("hidden", !project);

  syncProjectInUrl(project?.id || null);
  updateDocumentTitle();

  if (!project) return;

  // Always show the latest version after a (re)load; a rerun appends a new one.
  state.viewDraftId = null;

  els.detailTitle.textContent = project.title;
  els.detailMeta.textContent =
    `${phaseLabel(project.current_phase)} - ${t("created")} ${formatDate(project.created_at)} - ${t("updated")} ${formatDate(project.updated_at)}`;
  els.detailStatus.textContent = statusLabel(project.status);
  els.detailRequest.textContent = project.initial_request;
  els.requestSummaryPreview.textContent = project.initial_request.split("\n")[0];
  if (els.docTypeSelect) {
    els.docTypeSelect.value = project.document_type || "auto";
  }

  // The parallel loads below each repaint the status box as they resolve
  // (the pill can flip from the project status to "review needed", and the
  // message pops in and out). Keep the box invisible until the first full
  // render of a newly opened project so only the settled state ever paints.
  const projectChanged = state.renderedProjectId !== project.id;
  state.renderedProjectId = project.id;
  if (projectChanged) els.statusStrip.classList.add("loading");

  try {
    await Promise.all([
      loadProgress(),
      loadQuestions(),
      loadArtifacts(),
      loadReferences(),
      loadProjectSettings(),
      loadQuality(),
    ]);
    renderNextAction();
    renderDraftPreview();
    renderQuality();
    renderTabs();
    applyLayoutPhase();
  } finally {
    els.statusStrip.classList.remove("loading");
  }

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

async function loadQuality() {
  const project = selectedProject();
  if (!project) return;

  state.quality = null;
  state.quality = await api(`/projects/${project.id}/quality`);
  renderQuality();
}

function renderQuality() {
  if (!els.qualityPanel) return;
  const quality = state.quality;
  if (!quality || !latestDraft()) {
    els.qualityPanel.classList.add("hidden");
    els.qualityToggle?.classList.add("hidden");
    els.detailStatus.disabled = true;
    els.detailStatus.removeAttribute("title");
    els.detailStatus.removeAttribute("aria-expanded");
    return;
  }

  // The status pill doubles as a quality-panel toggle once a summary exists.
  els.detailStatus.disabled = false;
  els.detailStatus.title = t("qualitySummary");
  els.detailStatus.setAttribute("aria-expanded", String(state.qualityOpen));

  const needsReview = quality.status === "review_needed";
  // The panel stays collapsed behind this toggle; the status strip, detail
  // status, and run button already surface "review needed" on their own.
  if (els.qualityToggle) {
    els.qualityToggle.classList.remove("hidden", "review-needed", "ready");
    els.qualityToggle.classList.add(needsReview ? "review-needed" : "ready");
    const statusText = t(needsReview ? "qualityReviewNeeded" : "qualityReady");
    const warningCount = (quality.warnings || []).length;
    els.qualityToggle.textContent =
      needsReview && warningCount
        ? `${t("qualitySummary")} · ${statusText} ${warningCount}`
        : `${t("qualitySummary")} · ${statusText}`;
    els.qualityToggle.setAttribute("aria-expanded", String(state.qualityOpen));
  }

  els.qualityPanel.classList.remove("hidden", "review-needed", "ready");
  els.qualityPanel.classList.toggle("hidden", !state.qualityOpen);
  els.qualityPanel.classList.add(needsReview ? "review-needed" : "ready");
  els.qualityStatus.textContent = t(needsReview ? "qualityReviewNeeded" : "qualityReady");
  if (needsReview) {
    els.detailStatus.textContent = t("qualityReviewNeeded");
    setStripMessage(t("qualityReviewNeeded"));
    if (!els.runButton.disabled) els.runButton.textContent = t("improveDraft");
  } else {
    const project = selectedProject();
    if (project) els.detailStatus.textContent = statusLabel(project.status);
    if (!els.runButton.disabled) els.runButton.textContent = t("regenerateDraft");
  }

  const source = quality.source_quality || {};
  const citations = quality.citations || {};
  const evidence = quality.evidence || {};
  const writing = quality.writing_quality || {};
  const structure = quality.structure_quality || {};
  const review = quality.review || {};
  els.qualityStrongSources.textContent = String(source.strong_source_count || 0);
  els.qualityLowSources.textContent = String(source.low_quality_count || 0);
  els.qualityCitationCoverage.textContent =
    citations.cited_paragraph_percent == null ? "-" : `${citations.cited_paragraph_percent}%`;
  els.qualityEvidenceCoverage.textContent =
    evidence.verified_citation_percent == null ? "-" : `${evidence.verified_citation_percent}%`;
  els.qualityIssueCount.textContent = String(review.issue_count || 0);
  els.qualityWritingIssueCount.textContent = String(
    writing.active_issue_count ?? writing.issue_count ?? 0,
  );
  els.qualityStructureIssueCount.textContent = String(
    structure.active_issue_count ?? structure.issue_count ?? 0,
  );
  els.qualityWarnings.innerHTML = "";
  for (const warning of quality.warnings || []) {
    const item = document.createElement("li");
    item.textContent = t(`qualityWarning_${warning}`);
    els.qualityWarnings.append(item);
  }
  const linkedSections = new Set();
  for (const issue of qualityIssueDisplayList(writing.issues, 6)) {
    appendQualityIssueLink(issue, `writingIssue_${issue.type}`, linkedSections);
  }
  for (const issue of qualityIssueDisplayList(structure.issues, 6)) {
    appendQualityIssueLink(issue, `structureIssue_${issue.type}`, linkedSections);
  }
  const reviewTargets = review.target_issues || (review.revision_targets || []).map(
    (sectionId) => ({ type: "review_target", section_ids: [String(sectionId)], excerpts: [] }),
  );
  for (const reviewIssue of reviewTargets.slice(0, 4)) {
    const sectionId = qualityIssueTargetSection(reviewIssue);
    if (linkedSections.has(String(sectionId))) continue;
    appendQualityIssueLink(
      reviewIssue,
      (reviewIssue.excerpts || [])[0] ? "qualityReviewTargetDetail" : "qualityReviewTarget",
      linkedSections,
    );
  }
  const writingRepair = writing.repair || {};
  if (writingRepair.attempted) {
    const item = document.createElement("li");
    item.className = "quality-repair-summary";
    item.textContent = t("writingRepairSummary", {
      attempted: writingRepair.attempted_section_count || 0,
      repaired: writingRepair.repaired_section_count || 0,
    });
    els.qualityWarnings.append(item);
  }
  els.qualityWarnings.classList.toggle("hidden", !els.qualityWarnings.children.length);
}

function qualityIssueTargetSection(issue) {
  const ids = (issue?.section_ids || []).map(String).filter(Boolean);
  if (!ids.length) return "";
  return ["duplicate", "possible_contradiction"].includes(issue.type)
    ? ids[ids.length - 1]
    : ids[0];
}

function qualityIssueDisplayList(issues, limit) {
  return [...(issues || [])]
    .sort((left, right) => Number(left.decision?.decision === "waived") - Number(right.decision?.decision === "waived"))
    .slice(0, limit);
}

function appendQualityIssueLink(issue, labelKey, linkedSections) {
  const sectionId = qualityIssueTargetSection(issue);
  const sections = (issue.section_ids || []).map(String).join(", ") || "-";
  const label = t(labelKey, {
    sections,
    excerpt: (issue.excerpts || [""])[0],
  });
  const help = t(`issueHelp_${issue.type}`);
  const item = document.createElement("li");
  item.className = "quality-writing-detail";
  const decision = issue.decision || null;
  if (decision?.decision) item.classList.add(`quality-${decision.decision}`);
  if (!sectionId) {
    item.textContent = label;
    item.title = help;
  } else {
    const row = document.createElement("div");
    row.className = "quality-issue-row";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "quality-issue-link";
    button.textContent = label;
    button.title = t("jumpToQualityIssue", { id: sectionId });
    button.setAttribute("aria-label", `${label}. ${button.title}`);
    button.addEventListener("click", () => focusQualityIssue(issue));
    row.append(button);
    const helpBadge = document.createElement("span");
    helpBadge.className = "quality-issue-help";
    helpBadge.textContent = "?";
    helpBadge.title = help;
    helpBadge.setAttribute("aria-label", help);
    helpBadge.setAttribute("role", "img");
    row.append(helpBadge);
    const canRequestFix = hasStoredSectionDraft(sectionId);
    if (canRequestFix || (issue.issue_key && issue.type !== "review_target")) {
      const actions = document.createElement("span");
      actions.className = "quality-issue-actions";
      if (canRequestFix) {
        const fix = document.createElement("button");
        fix.type = "button";
        fix.className = "quality-decision-action quality-fix-action";
        fix.textContent = t("requestIssueFix");
        fix.addEventListener("click", () => openQualityIssueFeedback(issue));
        actions.append(fix);
      }
      if (issue.issue_key && issue.type !== "review_target" && decision?.decision) {
        const badge = document.createElement("span");
        badge.className = "quality-decision-badge";
        badge.textContent = t(
          decision.decision === "waived" ? "issueWaived" : "issueAcknowledged",
          { reason: decision.reason },
        );
        badge.title = badge.textContent;
        actions.append(badge);
        const clear = document.createElement("button");
        clear.type = "button";
        clear.className = "quality-decision-action";
        clear.textContent = t("clearIssueDecision");
        clear.addEventListener("click", () => clearQualityIssueDecision(issue));
        actions.append(clear);
      } else if (issue.issue_key && issue.type !== "review_target") {
        for (const [action, key] of [
          ["acknowledged", "acknowledgeIssue"],
          ["waived", "waiveIssue"],
        ]) {
          const actionButton = document.createElement("button");
          actionButton.type = "button";
          actionButton.className = "quality-decision-action";
          actionButton.textContent = t(key);
          actionButton.addEventListener("click", () => saveQualityIssueDecision(issue, action));
          actions.append(actionButton);
        }
      }
      row.append(actions);
    }
    item.append(row);
    linkedSections?.add(sectionId);
  }
  els.qualityWarnings.append(item);
}

function hasStoredSectionDraft(sectionId) {
  return state.artifacts.some(
    (artifact) =>
      artifact.type === "section_draft" &&
      String(artifact.content?.section?.id || "") === String(sectionId),
  );
}

async function refreshQualityDecisionState(summary) {
  state.quality = summary;
  state.projects = await api("/projects");
  renderProjects();
  renderQuality();
  renderStatusStrip();
}

async function saveQualityIssueDecision(issue, decision) {
  const project = selectedProject();
  if (!project || !issue.issue_key) return;
  const reason = window.prompt(t("issueDecisionReason"), issue.decision?.reason || "");
  if (!reason?.trim()) return;
  try {
    const summary = await api(
      `/projects/${project.id}/quality/issues/${encodeURIComponent(issue.issue_key)}`,
      {
        method: "PUT",
        body: JSON.stringify({ decision, reason: reason.trim() }),
      },
    );
    await refreshQualityDecisionState(summary);
    showToast(t("issueDecisionSaved"));
  } catch (error) {
    showToast(error.message, true);
  }
}

async function clearQualityIssueDecision(issue) {
  const project = selectedProject();
  if (!project || !issue.issue_key) return;
  try {
    const summary = await api(
      `/projects/${project.id}/quality/issues/${encodeURIComponent(issue.issue_key)}`,
      { method: "DELETE" },
    );
    await refreshQualityDecisionState(summary);
    showToast(t("issueDecisionCleared"));
  } catch (error) {
    showToast(error.message, true);
  }
}

function normalizeQualityExcerpt(value) {
  return String(value || "")
    .normalize("NFKC")
    .toLowerCase()
    .replace(/\[\[?\d+\]?\](?:\([^)]*\))?/g, " ")
    .replace(/\]\([^)]*\)/g, "]")
    .replace(/[^0-9a-z가-힣]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
}

function qualityIssueTextTarget(heading, issue) {
  if (!["duplicate", "possible_contradiction", "unsupported_overclaim", "long_sentence", "long_paragraph"].includes(issue.type)) {
    return heading;
  }
  const needle = normalizeQualityExcerpt((issue.excerpts || [""])[0]);
  if (!needle) return heading;
  const candidates = [];
  let sibling = heading.nextElementSibling;
  while (sibling && !sibling.matches("h1, h2, h3, h4, h5, h6")) {
    if (sibling.matches("p, li, blockquote, td")) candidates.push(sibling);
    candidates.push(...sibling.querySelectorAll("p, li, blockquote, td"));
    sibling = sibling.nextElementSibling;
  }
  const needleHead = needle.slice(0, Math.min(90, needle.length));
  return (
    candidates.find((candidate) => {
      const haystack = normalizeQualityExcerpt(candidate.textContent);
      return (
        haystack.includes(needleHead) ||
        (haystack.length >= 20 && needle.includes(haystack.slice(0, 60)))
      );
    }) || heading
  );
}

async function prepareQualityIssueLocation(issue) {
  const sectionId = qualityIssueTargetSection(issue);
  if (!sectionId) return null;
  // Quality always describes the latest draft. Leave an older version or raw
  // view before locating its rendered section nodes.
  state.viewDraftId = null;
  state.draftView = "rendered";
  renderDraftPreview();
  await new Promise((resolve) => window.requestAnimationFrame(resolve));
  const heading = [...els.draftPreview.querySelectorAll("[data-section-id]")].find(
    (node) => node.dataset.sectionId === sectionId,
  );
  return heading
    ? { sectionId, heading, target: qualityIssueTextTarget(heading, issue) }
    : null;
}

function highlightQualityLocation(location) {
  for (const node of els.draftPreview.querySelectorAll(".quality-focus")) {
    node.classList.remove("quality-focus");
  }
  location.target.classList.add("quality-focus");
  location.target.setAttribute("tabindex", "-1");
  location.target.scrollIntoView({ behavior: "smooth", block: "center" });
  location.target.focus({ preventScroll: true });
  window.setTimeout(() => {
    location.target.classList.remove("quality-focus");
    location.target.removeAttribute("tabindex");
  }, 3200);
}

async function focusQualityIssue(issue) {
  const location = await prepareQualityIssueLocation(issue);
  if (!location) {
    showToast(t("qualityIssueNotFound"), true);
    return;
  }
  highlightQualityLocation(location);
}

async function openQualityIssueFeedback(issue) {
  const location = await prepareQualityIssueLocation(issue);
  if (!location) {
    showToast(t("qualityIssueNotFound"), true);
    return;
  }
  highlightQualityLocation(location);
  const comment = t("qualityFeedbackTemplate", {
    issue: t(`issueName_${issue.type}`),
    excerpt: (issue.excerpts || [""])[0] || "-",
    sections: (issue.section_ids || []).map(String).join(", ") || location.sectionId,
  });
  const panel = await toggleSectionFeedbackPanel(
    location.sectionId,
    location.heading,
    comment,
  );
  panel?.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function loadReferences() {
  const project = selectedProject();
  if (!project) return;

  state.references = await api(`/projects/${project.id}/references`);
  renderReferences();
}

function renderReferences() {
  els.referenceList.innerHTML = "";
  if (els.styleSampleList) els.styleSampleList.innerHTML = "";
  const contentRefs = state.references.filter((ref) => ref.kind !== "style");
  const styleRefs = state.references.filter((ref) => ref.kind === "style");
  if (!contentRefs.length) {
    const empty = document.createElement("p");
    empty.className = "item-meta";
    empty.textContent = t("noReferences");
    els.referenceList.append(empty);
  }
  if (els.styleSampleList && !styleRefs.length) {
    const empty = document.createElement("p");
    empty.className = "item-meta";
    empty.textContent = t("noStyleSamples");
    els.styleSampleList.append(empty);
  }

  for (const reference of state.references) {
    const target =
      reference.kind === "style" ? els.styleSampleList : els.referenceList;
    if (!target) continue;
    const item = document.createElement("div");
    item.className = "reference-item";

    const icon = document.createElement("span");
    icon.textContent =
      reference.kind === "url" ? "🔗" : reference.kind === "style" ? "✍️" : "📄";
    item.append(icon);

    if (reference.kind === "url") {
      const link = document.createElement("a");
      link.href = reference.source;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = reference.title || reference.source;
      item.append(link);
    } else {
      const name = document.createElement("span");
      name.textContent = reference.source;
      item.append(name);
    }

    if (reference.status === "error") {
      const error = document.createElement("span");
      error.className = "reference-error";
      error.textContent = reference.error || t("error");
      item.append(error);
    }

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "reference-delete";
    remove.title = t("removeReference");
    remove.setAttribute("aria-label", t("removeReference"));
    remove.textContent = "✕";
    remove.addEventListener("click", () => deleteReference(reference.id));
    item.append(remove);

    target.append(item);
  }
}

async function deleteReference(referenceId) {
  const project = selectedProject();
  if (!project) return;
  try {
    await api(`/projects/${project.id}/references/${referenceId}`, { method: "DELETE" });
    showToast(t("referenceRemoved"));
    await loadReferences();
  } catch (error) {
    showToast(error.message, true);
  }
}

function settingToSelectValue(value) {
  if (value === true) return "on";
  if (value === false) return "off";
  return "default";
}

function selectValueToSetting(value) {
  if (value === "on") return true;
  if (value === "off") return false;
  return null;
}

async function loadDocTypes() {
  try {
    state.docTypes = await api("/doc-types");
  } catch {
    state.docTypes = [];
  }
  populateDocTypeSelects();
}

function populateDocTypeSelects() {
  for (const select of [els.projectDocType, els.docTypeSelect]) {
    if (!select) continue;
    const current = select.value || "auto";
    select.innerHTML = "";
    const auto = document.createElement("option");
    auto.value = "auto";
    auto.textContent = t("autoDetect");
    select.append(auto);
    for (const type of state.docTypes) {
      const option = document.createElement("option");
      option.value = type.key;
      option.textContent = state.language === "ko" ? type.label_ko : type.label_en;
      select.append(option);
    }
    select.value = [...select.options].some((option) => option.value === current)
      ? current
      : "auto";
  }
}

async function saveDocType() {
  const project = selectedProject();
  if (!project || !els.docTypeSelect) return;
  const value = els.docTypeSelect.value || "auto";
  if ((project.document_type || "auto") === value) return;
  try {
    await api(`/projects/${project.id}`, {
      method: "PATCH",
      body: JSON.stringify({ document_type: value }),
    });
    showToast(t("docTypeSaved"));
    await loadProjects();
    await loadProjectSettings().catch(() => {});
  } catch (error) {
    showToast(error.message, true);
    els.docTypeSelect.value = project.document_type || "auto";
  }
}

async function loadProjectSettings() {
  const project = selectedProject();
  if (!project) return;
  state.projectSettings = await api(`/projects/${project.id}/settings`);
  renderProjectSettings();
}

function renderProjectSettings() {
  const config = state.projectSettings;
  if (!config) return;
  if (els.searchEnabledSelect) {
    els.searchEnabledSelect.value = settingToSelectValue(config.search_enabled);
  }
  if (els.sectionSearchSelect) {
    els.sectionSearchSelect.value = settingToSelectValue(config.section_search_enabled);
  }
  const engines = Array.isArray(config.search_engines) ? config.search_engines : [];
  if (els.searchEngine1Select) {
    els.searchEngine1Select.value = engines[0] || "default";
  }
  if (els.searchEngine2Select) {
    els.searchEngine2Select.value = engines[1] || "none";
  }
  if (els.searchEngine3Select) {
    els.searchEngine3Select.value = engines[2] || "none";
  }
  if (els.searchHeadlessSelect) {
    els.searchHeadlessSelect.value = settingToSelectValue(config.search_headless);
  }
  if (els.searchStealthSelect) {
    els.searchStealthSelect.value = settingToSelectValue(config.search_stealth);
  }
  if (els.searchLocaleSelect) {
    els.searchLocaleSelect.value = config.search_locale || "default";
  }
  if (els.searchQueryLanguageSelect) {
    els.searchQueryLanguageSelect.value = config.search_query_language || "default";
  }
  if (els.citationStyleSelect) {
    els.citationStyleSelect.value = config.citation_style || "default";
  }
  if (els.targetLengthInput) {
    els.targetLengthInput.value = config.target_length ?? "";
    els.targetLengthInput.placeholder = t("targetLengthAuto");
  }
  applySettingDefaultLabels(config.defaults);
}

// "Use default" alone hides what the run would actually do, so each default
// option is relabeled with the server-resolved value, e.g. "Use default (On)".
function applySettingDefaultLabels(defaults) {
  if (!defaults) return;
  const onOff = (value) => t(value ? "on" : "off");
  const engineNames = { daum: "Daum", bing: "Bing", google: "Google" };
  const engineChain = (defaults.search_engines || [])
    .map((engine) => engineNames[engine] || engine)
    .join(" → ");
  const queryLangLabel = {
    native: t("queryLangNative"),
    english: t("queryLangEnglish"),
    both: t("queryLangBoth"),
  }[defaults.search_query_language];
  const citationLabel = defaults.citation_style
    ? t(defaults.citation_style === "author_date" ? "citationAuthorDate" : "citationNumeric")
    : "";
  const labelled = [
    [els.searchEnabledSelect, onOff(defaults.search_enabled)],
    [els.sectionSearchSelect, onOff(defaults.section_search_enabled)],
    [els.searchEngine1Select, engineChain],
    [els.searchHeadlessSelect, onOff(defaults.search_headless)],
    [els.searchStealthSelect, onOff(defaults.search_stealth)],
    [els.searchLocaleSelect, defaults.search_locale || ""],
    [els.searchQueryLanguageSelect, queryLangLabel || ""],
    [els.citationStyleSelect, citationLabel],
  ];
  for (const [select, label] of labelled) {
    const option = select?.querySelector('option[value="default"]');
    if (option && label) option.textContent = `${t("useDefault")} (${label})`;
  }
}

async function saveProjectSettings() {
  const project = selectedProject();
  if (!project) return;
  const citationStyle = els.citationStyleSelect?.value;
  const targetLengthRaw = parseInt(els.targetLengthInput?.value, 10);
  const searchLocale = els.searchLocaleSelect?.value;
  const queryLanguage = els.searchQueryLanguageSelect?.value;
  const engineSlots = [
    els.searchEngine1Select?.value,
    els.searchEngine2Select?.value,
    els.searchEngine3Select?.value,
  ];
  // Slot 1 "default" means "use the global default" (send null). Otherwise
  // build the priority list from the slots, skipping none/default + dupes.
  let searchEngines = null;
  if (engineSlots[0] && engineSlots[0] !== "default") {
    searchEngines = [];
    for (const slot of engineSlots) {
      if (slot && slot !== "default" && slot !== "none" && !searchEngines.includes(slot)) {
        searchEngines.push(slot);
      }
    }
    if (searchEngines.length === 0) searchEngines = null;
  }
  const payload = {
    search_enabled: selectValueToSetting(els.searchEnabledSelect.value),
    section_search_enabled: selectValueToSetting(els.sectionSearchSelect.value),
    citation_style: citationStyle === "default" ? null : citationStyle || null,
    target_length: Number.isFinite(targetLengthRaw) && targetLengthRaw > 0
      ? Math.min(Math.max(targetLengthRaw, 100), 200000)
      : null,
    search_engines: searchEngines,
    search_headless: selectValueToSetting(els.searchHeadlessSelect.value),
    search_stealth: selectValueToSetting(els.searchStealthSelect.value),
    search_locale: searchLocale === "default" ? null : searchLocale || null,
    search_query_language: queryLanguage === "default" ? null : queryLanguage || null,
  };
  try {
    state.projectSettings = await api(`/projects/${project.id}/settings`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    renderProjectSettings();
    showToast(t("settingsSaved"));
  } catch (error) {
    showToast(error.message, true);
    await loadProjectSettings().catch(() => {});
  }
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
    const isSelected = step.phase === state.selectedStepPhase;
    compact.classList.toggle("selected", isSelected);
    compact.setAttribute("role", "button");
    compact.setAttribute("tabindex", "0");
    compact.setAttribute("aria-pressed", String(isSelected));
    compact.innerHTML = `
      <strong></strong>
      <span></span>
    `;
    compact.querySelector("strong").textContent = phaseLabel(step.phase, step.label);
    compact.querySelector("span").textContent = `${statusLabel(step.status)} · ${stepDuration(step)}`;
    const toggleStepDetail = () => {
      state.selectedStepPhase =
        state.selectedStepPhase === step.phase ? null : step.phase;
      renderProgress();
    };
    compact.addEventListener("click", toggleStepDetail);
    compact.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggleStepDetail();
      }
    });
    if (step.progress && step.progress.total) {
      const { done, total } = step.progress;
      const fraction = total ? Math.round((done / total) * 100) : 0;
      const sub = document.createElement("div");
      sub.className = "step-subprogress";
      sub.innerHTML = `
        <div class="step-subtrack"><div class="step-subfill"></div></div>
        <span class="step-subcount"></span>
      `;
      sub.querySelector(".step-subfill").style.width = `${fraction}%`;
      sub.querySelector(".step-subcount").textContent = `${done}/${total}`;
      compact.append(sub);
    }
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

  const doneCount = progress.steps.filter((step) => step.status === "completed").length;
  els.pipelineSummaryText.textContent =
    `${statusLabel(progress.status)} · ${doneCount}/${progress.steps.length}`;

  renderStatusStrip();
  applyLayoutPhase();
  renderStepDetail();
}

function renderStepDetail() {
  if (!els.stepDetail) return;
  const step = state.progress?.steps?.find(
    (candidate) => candidate.phase === state.selectedStepPhase,
  );
  if (!state.selectedStepPhase || !step) {
    els.stepDetail.classList.add("hidden");
    els.stepDetail.innerHTML = "";
    state.lastStepDetailKey = null;
    return;
  }

  // Skip the rebuild when nothing changed so polling (1.2s) does not reset the
  // detail body's scroll position. Language is part of the key because the
  // rendered labels are localized even though the raw step data is not.
  const key = `${state.language}|${step.phase}|${JSON.stringify(step)}`;
  if (state.lastStepDetailKey === key) return;

  const previousBody = els.stepDetail.querySelector(".step-detail-body");
  const previousScroll = previousBody ? previousBody.scrollTop : 0;
  state.lastStepDetailKey = key;

  els.stepDetail.classList.remove("hidden");
  els.stepDetail.innerHTML = `
    <div class="step-detail-head">
      <p class="item-title"></p>
      <div class="inline-controls">
        <button type="button" class="secondary rerun-step"></button>
        <button type="button" class="icon-button step-detail-close"></button>
      </div>
    </div>
    <p class="item-meta"></p>
    <div class="step-detail-body"></div>
  `;
  els.stepDetail.querySelector(".item-title").textContent = phaseLabel(step.phase, step.label);
  els.stepDetail.querySelector(".item-meta").textContent =
    `${statusLabel(step.status)} - ${t("started")} ${formatDate(step.created_at)} - ${t("completed")} ${formatDate(step.completed_at)} - ${t("duration")} ${stepDuration(step)}`;

  const rerunButton = els.stepDetail.querySelector(".rerun-step");
  rerunButton.textContent = t("rerunFromHere");
  rerunButton.addEventListener("click", () => {
    rerunFromStep(step.phase).catch((error) => showToast(error.message, true));
  });

  const closeButton = els.stepDetail.querySelector(".step-detail-close");
  closeButton.textContent = "✕";
  closeButton.setAttribute("aria-label", t("close"));
  closeButton.addEventListener("click", () => {
    state.selectedStepPhase = null;
    renderProgress();
  });

  const body = els.stepDetail.querySelector(".step-detail-body");
  // renderStepDetails already renders the error block for failed steps.
  body.insertAdjacentHTML("beforeend", renderStepDetails(step));
  body.scrollTop = previousScroll;
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
  const project = selectedProject();
  const idleLabel = project?.status === "review_needed" || state.quality?.status === "review_needed"
    ? t("improveDraft")
    : latestDraft()
      ? t("regenerateDraft")
      : t("startWriting");
  els.runButton.textContent = isRunning ? t("writing") : idleLabel;
  if (els.cancelButton) {
    els.cancelButton.classList.toggle("hidden", !isRunning);
    if (isRunning) {
      els.cancelButton.disabled = false;
      els.cancelButton.textContent = t("cancelWriting");
    }
  }
}

async function cancelWritingRun() {
  const project = selectedProject();
  if (!project) return;
  els.cancelButton.disabled = true;
  els.cancelButton.textContent = t("cancelling");
  try {
    await api(`/projects/${project.id}/cancel`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    showToast(t("cancelRequested"));
  } catch (error) {
    showToast(error.message, true);
    els.cancelButton.disabled = false;
    els.cancelButton.textContent = t("cancelWriting");
  }
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
  return DocuGenMarkdown.escapeHtml(value);
}

function inlineMarkdown(value) {
  return DocuGenMarkdown.inlineMarkdown(value);
}

function renderMarkdown(markdown) {
  return DocuGenMarkdown.renderMarkdown(markdown, { emptyMessage: t("draftEmpty") });
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

function renderSourceLinks(sources) {
  if (!sources || sources.length === 0) {
    return `<p class="item-meta">${escapeHtml(t("noSourcesFound"))}</p>`;
  }
  return `<ul class="source-list">${sources
    .map(
      (source) =>
        `<li><a href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer">${escapeHtml(source.title || source.url)}</a>${source.summary ? `<span class="source-summary">${escapeHtml(source.summary)}</span>` : ""}</li>`,
    )
    .join("")}</ul>`;
}

function renderUsedSources(sources) {
  if (!sources || sources.length === 0) {
    return `<p class="item-meta">${escapeHtml(t("noSourcesUsed"))}</p>`;
  }
  return `<p class="item-meta">${escapeHtml(t("usedSources"))}</p><ul class="source-list">${sources
    .map(
      (source) =>
        `<li><a href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer">${escapeHtml(source.title || source.url)}</a>${source.from_chapter_research ? ` <span class="source-badge">${escapeHtml(t("fromChapterResearch"))}</span>` : ""}</li>`,
    )
    .join("")}</ul>`;
}

const ENGINE_LABELS = {
  daum: "Daum",
  bing: "Bing",
  google: "Google",
  google_pse: "Google PSE",
  duckduckgo: "DuckDuckGo",
};

function engineLabel(name) {
  return ENGINE_LABELS[name] || name || "";
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
    case "research": {
      const researchQueries =
        details.queries && details.queries.length
          ? details.queries
          : details.query
            ? [details.query]
            : [];
      return [
        renderKeyValueList([
          [t("querySource"), details.query_source],
          [t("engine"), (details.engines || []).map(engineLabel).join(", ")],
          [t("sources"), details.source_count],
          [t("searchError"), details.error],
        ]),
        researchQueries.length
          ? `<p class="item-meta">${escapeHtml(t("queries"))}</p>${renderBullets(researchQueries)}`
          : "",
        details.sources?.length
          ? `<ul>${details.sources
              .map(
                (source) =>
                  `<li><a href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer">${escapeHtml(source.title || source.url)}</a></li>`,
              )
              .join("")}</ul>`
          : "",
      ].join("");
    }
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
    case "chapter_research":
      return [
        renderKeyValueList([
          [t("chapters"), details.chapter_count],
          [t("sources"), details.source_count],
          [t("searchError"), details.error],
        ]),
        `<div class="preview-list">${(details.chapters || [])
          .map(
            (chapter) => `<article>
              <strong>${escapeHtml([chapter.id, chapter.title].filter(Boolean).join(". "))}</strong>
              <p class="item-meta">${escapeHtml(t("query"))}: ${escapeHtml(chapter.query || "-")}${chapter.engine ? ` · ${escapeHtml(t("engine"))}: ${escapeHtml(engineLabel(chapter.engine))}` : ""}</p>
              ${chapter.error ? `<p class="item-meta">${escapeHtml(t("searchError"))}: ${escapeHtml(chapter.error)}</p>` : ""}
              ${renderSourceLinks(chapter.sources)}
            </article>`,
          )
          .join("")}</div>`,
      ].join("");
    case "section_writing":
      return [
        renderKeyValueList([
          [t("sectionDrafts"), details.section_draft_count],
          [t("chapterDigests"), details.chapter_digest_count],
          [t("glossary"), (details.glossary_terms || []).join(", ")],
        ]),
        details.topup_searches?.length
          ? `<p class="item-meta">${escapeHtml(t("topupSearches"))}</p><ul>${details.topup_searches
              .map(
                (s) =>
                  `<li>${escapeHtml(s.query || "-")} · ${escapeHtml(t("sources"))}: ${escapeHtml(s.source_count ?? 0)}${s.engines?.length ? ` · ${escapeHtml(t("engine"))}: ${escapeHtml(s.engines.map(engineLabel).join(", "))}` : ""}${s.error ? ` · ${escapeHtml(t("searchError"))}: ${escapeHtml(s.error)}` : ""}</li>`,
              )
              .join("")}</ul>`
          : "",
        `<div class="preview-list">${(details.section_drafts || [])
          .map(
            (draft) =>
              `<article><strong>${escapeHtml(draft.title)}</strong><p>${escapeHtml(draft.preview)}</p>${renderUsedSources(draft.sources)}</article>`,
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
          [t("smoothedSeams"), details.smoothed_seams],
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
      const answerRow = document.createElement("div");
      answerRow.className = "answer-row";
      answerRow.innerHTML = `
        <input aria-label="${escapeHtml(t("answer"))}" placeholder="${escapeHtml(t("answer"))}" />
      `;
      const input = answerRow.querySelector("input");
      input.value = getAnswerDraft(question.id);
      input.addEventListener("input", () => {
        setAnswerDraft(question.id, input.value);
      });
      input.addEventListener("keydown", async (event) => {
        if (event.key !== "Enter") return;
        event.preventDefault();
        await saveAllAnswers();
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

  if (sorted.some((question) => question.status === "pending")) {
    const batchBar = document.createElement("div");
    batchBar.className = "answer-batch-actions";
    batchBar.innerHTML = `
      <button type="button" class="save-all">${escapeHtml(t("saveAllAnswers"))}</button>
    `;
    batchBar.querySelector(".save-all").addEventListener("click", async () => {
      await saveAllAnswers();
    });
    els.questionList.append(batchBar);
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

function pendingAnswerEntries() {
  return state.questions
    .filter((question) => question.status === "pending")
    .map((question) => ({
      id: question.id,
      answer: getAnswerDraft(question.id).trim(),
    }))
    .filter((entry) => entry.answer);
}

async function saveAllAnswers({ startRun = false } = {}) {
  const project = selectedProject();
  if (!project) return;

  const entries = pendingAnswerEntries();
  if (entries.length === 0) {
    showToast(t("noAnswersToSave"), true);
    return;
  }

  try {
    for (const entry of entries) {
      await api(`/projects/${project.id}/questions/${entry.id}/answer`, {
        method: "POST",
        body: JSON.stringify({ answer: entry.answer }),
      });
      clearAnswerDraft(entry.id);
    }
  } catch (error) {
    showToast(error.message, true);
    await Promise.all([loadQuestions(), loadProjects()]).catch(() => {});
    return;
  }

  showToast(t("answersSaved", { count: entries.length }));
  await Promise.all([loadQuestions(), loadProjects()]);
  if (startRun) {
    await startWritingRun();
  }
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
  const draft = currentDraft();
  renderVersions();
  updateVersionsVisibility();
  if (!draft) {
    state.compareSelection = [];
    els.draftStatus.textContent = t("noDraft");
    if (els.formViewButton) {
      els.formViewButton.disabled = true;
    }
    els.draftToc.classList.add("hidden");
    els.draftToc.innerHTML = "";
    els.draftViewer.classList.add("no-toc");
    els.draftPreview.classList.add("markdown-body");
    els.draftPreview.classList.remove("raw", "compare-view");
    els.draftPreview.textContent = t("draftEmpty");
    return;
  }
  if (els.formViewButton) {
    els.formViewButton.disabled = false;
  }

  // compareDrafts() drops stale ids; two valid selections turn on compare mode.
  const compareSelected = compareDrafts();
  if (compareSelected.length === 2) {
    const [fromDraft, toDraft] =
      compareSelected[0].version < compareSelected[1].version
        ? [compareSelected[0], compareSelected[1]]
        : [compareSelected[1], compareSelected[0]];
    els.draftStatus.textContent = `v${fromDraft.version} ↔ v${toDraft.version}`;
    els.draftToc.classList.add("hidden");
    els.draftToc.innerHTML = "";
    els.draftViewer.classList.add("no-toc");
    els.draftPreview.classList.remove("markdown-body", "raw");
    els.draftPreview.classList.add("compare-view");
    renderCompareView(fromDraft, toDraft);
    return;
  }
  els.draftPreview.classList.remove("compare-view");

  const drafts = draftVersions();
  const isLatest = drafts[0] && draft.id === drafts[0].id;
  els.draftStatus.textContent = isLatest ? `v${draft.version}` : `v${draft.version} · ${t("viewVersion")}`;
  const markdown = artifactBodyText(draft);
  els.draftViewToggle.textContent = state.draftView === "rendered" ? t("raw") : t("rendered");
  els.draftPreview.classList.toggle("markdown-body", state.draftView === "rendered");
  els.draftPreview.classList.toggle("raw", state.draftView !== "rendered");
  if (state.draftView === "rendered") {
    const rendered = renderMarkdown(markdown);
    els.draftPreview.innerHTML = rendered.html;
    els.draftToc.innerHTML = renderToc(rendered.toc);
    els.draftToc.classList.toggle("hidden", rendered.toc.length === 0);
    els.draftViewer.classList.toggle("no-toc", rendered.toc.length === 0);
    attachSectionFeedbackButtons();
    renderMermaidDiagrams();
    renderMathExpressions();
  } else {
    els.draftToc.classList.add("hidden");
    els.draftToc.innerHTML = "";
    els.draftViewer.classList.add("no-toc");
    els.draftPreview.textContent = markdown;
  }
}

function conditionsSummary(conditions) {
  if (!conditions) return "";
  const parts = [
    `${t("condSearch")} ${conditions.search_enabled ? t("on") : t("off")}`,
    `${t("condCitations")} ${conditions.citations_enabled === false ? t("off") : t("on")}`,
    `${t("condRefs")} ${conditions.reference_count ?? 0}`,
  ];
  if (conditions.citations_enabled !== false && conditions.citation_style) {
    parts.push(
      conditions.citation_style === "author_date"
        ? t("citationAuthorDate")
        : t("citationNumeric"),
    );
  }
  if (conditions.model) parts.push(conditions.model);
  return parts.join(" · ");
}

function updateVersionsVisibility() {
  const drafts = draftVersions();
  if (els.versionsButton) {
    els.versionsButton.disabled = drafts.length === 0;
  }
  els.versionList.classList.toggle(
    "hidden",
    !state.versionsOpen || drafts.length === 0,
  );
}

function renderVersions() {
  const drafts = draftVersions();
  els.versionList.innerHTML = "";
  if (drafts.length === 0) {
    els.versionList.innerHTML = `<p class="item-meta">${escapeHtml(t("noVersions"))}</p>`;
    return;
  }

  const head = document.createElement("div");
  head.className = "version-list-head";
  const heading = document.createElement("p");
  heading.className = "version-title";
  heading.textContent = t("versions");
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "icon-button";
  closeBtn.textContent = "✕";
  closeBtn.setAttribute("aria-label", t("close"));
  closeBtn.addEventListener("click", () => {
    state.versionsOpen = false;
    updateVersionsVisibility();
  });
  head.append(heading, closeBtn);
  els.versionList.append(head);

  const viewed = currentDraft();
  const selectedDrafts = compareDrafts();
  const selectedIds = selectedDrafts.map((draft) => draft.id);
  if (selectedDrafts.length === 1) {
    const hint = document.createElement("p");
    hint.className = "item-meta compare-hint";
    hint.textContent = t("comparePickSecond", { version: selectedDrafts[0].version });
    els.versionList.append(hint);
  }
  for (const draft of drafts) {
    const isLatest = draft.id === drafts[0].id;
    const isViewing = viewed && draft.id === viewed.id;

    const row = document.createElement("div");
    row.className = "version-item";
    row.classList.toggle("viewing", Boolean(isViewing));
    row.classList.toggle("comparing", selectedIds.includes(draft.id));

    const meta = document.createElement("div");
    meta.className = "version-meta";
    const title = document.createElement("p");
    title.className = "version-title";
    title.textContent = `v${draft.version}${isLatest ? ` · ${t("latestBadge")}` : ""}`;
    const restoredFrom = draft.content?.restored_from;
    if (restoredFrom) {
      const tag = document.createElement("span");
      tag.className = "version-restored";
      tag.textContent = ` (${t("restoredFrom", { version: restoredFrom })})`;
      title.append(tag);
    }
    const sub = document.createElement("p");
    sub.className = "item-meta";
    const cond = conditionsSummary(draft.content?.conditions);
    sub.textContent = `${formatDate(draft.created_at)}${cond ? ` · ${cond}` : ""}`;
    meta.append(title, sub);

    const actions = document.createElement("div");
    actions.className = "version-actions";
    const viewBtn = document.createElement("button");
    viewBtn.type = "button";
    viewBtn.className = "secondary";
    viewBtn.textContent = t("viewVersion");
    viewBtn.disabled = Boolean(isViewing);
    viewBtn.addEventListener("click", () => {
      state.compareSelection = [];
      state.viewDraftId = draft.id;
      renderDraftPreview();
    });
    actions.append(viewBtn);
    const compareBtn = document.createElement("button");
    compareBtn.type = "button";
    const isSelected = selectedIds.includes(draft.id);
    compareBtn.className = "secondary";
    compareBtn.classList.toggle("compare-selected", isSelected);
    compareBtn.setAttribute("aria-pressed", String(isSelected));
    compareBtn.textContent = isSelected ? `✓ ${t("compare")}` : t("compare");
    compareBtn.addEventListener("click", () => {
      toggleCompareSelection(draft.id);
      renderDraftPreview();
    });
    actions.append(compareBtn);
    if (!isLatest) {
      const restoreBtn = document.createElement("button");
      restoreBtn.type = "button";
      restoreBtn.textContent = t("restoreVersion");
      restoreBtn.addEventListener("click", () => restoreVersion(draft.id));
      actions.append(restoreBtn);
    }

    row.append(meta, actions);
    els.versionList.append(row);
  }
}

async function restoreVersion(artifactId) {
  const project = selectedProject();
  if (!project) return;
  try {
    await api(`/projects/${project.id}/drafts/${artifactId}/restore`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    state.viewDraftId = null;
    state.compareSelection = [];
    showToast(t("restoredToast"));
    await loadArtifacts();
    renderDraftPreview();
  } catch (error) {
    showToast(error.message, true);
  }
}

// The drafts currently picked for comparison (0-2). Also prunes selections that
// no longer exist so a reload or restore can't leave a dangling id behind.
function compareDrafts() {
  const drafts = draftVersions();
  const valid = state.compareSelection.filter((id) => drafts.some((draft) => draft.id === id));
  if (valid.length !== state.compareSelection.length) {
    state.compareSelection = valid;
  }
  return valid.map((id) => drafts.find((draft) => draft.id === id));
}

// Toggles a draft in the comparison set, keeping at most the two most recent
// picks so a third selection slides the window forward.
function toggleCompareSelection(id) {
  const index = state.compareSelection.indexOf(id);
  if (index >= 0) {
    state.compareSelection.splice(index, 1);
    return;
  }
  state.compareSelection.push(id);
  while (state.compareSelection.length > 2) {
    state.compareSelection.shift();
  }
}

// Splits markdown into sections keyed on their heading. A section spans from a
// heading line to the next heading; text before the first heading is a
// preamble (heading null). Fenced code blocks are skipped so a `#` comment
// inside them is not mistaken for a heading.
function splitMarkdownSections(markdown) {
  const lines = String(markdown || "").split("\n");
  const sections = [];
  let current = { heading: null, numericId: null, titleKey: null, lines: [] };
  let inFence = false;

  const finalize = () => {
    const body = current.lines.join("\n");
    if (current.heading === null && body.trim() === "") return;
    sections.push({
      heading: current.heading,
      numericId: current.numericId,
      titleKey: current.titleKey,
      body,
    });
  };

  for (const line of lines) {
    if (/^\s*```/.test(line)) {
      inFence = !inFence;
    } else if (!inFence && /^#{1,6}\s/.test(line)) {
      finalize();
      const text = line.replace(/^#{1,6}\s+/, "").trim();
      const numericId = text.match(/^(\d+(?:\.\d+)*)\s+/)?.[1] || null;
      current = {
        heading: text,
        numericId,
        titleKey: normalizeSectionHeadingText(text),
        lines: [line],
      };
      continue;
    }
    current.lines.push(line);
  }
  finalize();
  return sections;
}

// Pairs base sections with target sections across three passes so re-numbering
// and title edits still line up: exact match, then title-only, then id-only.
function matchSections(baseSections, targetSections) {
  const pairs = [];
  const baseUsed = new Array(baseSections.length).fill(false);
  const targetUsed = new Array(targetSections.length).fill(false);

  const runPass = (predicate) => {
    for (let i = 0; i < baseSections.length; i++) {
      if (baseUsed[i]) continue;
      for (let j = 0; j < targetSections.length; j++) {
        if (targetUsed[j]) continue;
        if (predicate(baseSections[i], targetSections[j])) {
          baseUsed[i] = true;
          targetUsed[j] = true;
          pairs.push({ base: baseSections[i], target: targetSections[j] });
          break;
        }
      }
    }
  };

  runPass((b, t) => b.numericId === t.numericId && b.titleKey === t.titleKey);
  runPass((b, t) => b.titleKey !== null && b.titleKey === t.titleKey);
  runPass((b, t) => b.numericId !== null && b.numericId === t.numericId);

  const removed = baseSections.filter((_, i) => !baseUsed[i]);
  const added = targetSections.filter((_, j) => !targetUsed[j]);
  return { pairs, removed, added };
}

// Classic LCS diff over two token arrays. Guards against pathological inputs by
// falling back to a full replacement when the DP table would get too large.
function lcsDiff(tokensA, tokensB) {
  const n = tokensA.length;
  const m = tokensB.length;
  if (n * m > 500000) {
    return [
      ...tokensA.map((token) => ({ type: "del", token })),
      ...tokensB.map((token) => ({ type: "ins", token })),
    ];
  }
  const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] =
        tokensA[i] === tokensB[j]
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const result = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (tokensA[i] === tokensB[j]) {
      result.push({ type: "same", token: tokensA[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      result.push({ type: "del", token: tokensA[i] });
      i++;
    } else {
      result.push({ type: "ins", token: tokensB[j] });
      j++;
    }
  }
  while (i < n) {
    result.push({ type: "del", token: tokensA[i] });
    i++;
  }
  while (j < m) {
    result.push({ type: "ins", token: tokensB[j] });
    j++;
  }
  return result;
}

function tokenizeWords(text) {
  return text.split(/(\s+)/).filter(Boolean);
}

// Turns a line-level lcsDiff into aligned side-by-side rows. Each row carries a
// left cell (same/del parts) and a right cell (same/ins parts). A deletion run
// immediately followed by an insertion run is a replacement, re-diffed at the
// word level and split so shared words stay put while edits highlight per side.
function alignDiffRows(lineDiff) {
  const runs = [];
  for (const tok of lineDiff) {
    const last = runs[runs.length - 1];
    if (last && last.type === tok.type) last.text += tok.token;
    else runs.push({ type: tok.type, text: tok.token });
  }

  const pushPart = (cell, type, text) => {
    if (!text) return;
    const last = cell[cell.length - 1];
    if (last && last.type === type) last.text += text;
    else cell.push({ type, text });
  };

  const rows = [];
  for (let r = 0; r < runs.length; r++) {
    const run = runs[r];
    const next = runs[r + 1];
    if (run.type === "same") {
      rows.push({
        kind: "same",
        left: [{ type: "same", text: run.text }],
        right: [{ type: "same", text: run.text }],
      });
    } else if (run.type === "del" && next && next.type === "ins") {
      const wordDiff = lcsDiff(tokenizeWords(run.text), tokenizeWords(next.text));
      const left = [];
      const right = [];
      for (const w of wordDiff) {
        if (w.type === "same") {
          pushPart(left, "same", w.token);
          pushPart(right, "same", w.token);
        } else if (w.type === "del") {
          pushPart(left, "del", w.token);
        } else {
          pushPart(right, "ins", w.token);
        }
      }
      rows.push({ kind: "change", left, right });
      r++;
    } else if (run.type === "del") {
      rows.push({ kind: "del", left: [{ type: "del", text: run.text }], right: [] });
    } else {
      rows.push({ kind: "ins", left: [], right: [{ type: "ins", text: run.text }] });
    }
  }

  // Drop the phantom trailing newline that line tokenization appended.
  const lastRow = rows[rows.length - 1];
  if (lastRow) {
    for (const cell of [lastRow.left, lastRow.right]) {
      const lastPart = cell[cell.length - 1];
      if (!lastPart) continue;
      lastPart.text = lastPart.text.replace(/\n$/, "");
      if (!lastPart.text) cell.pop();
    }
  }
  return rows;
}

// Aligned rows for a changed section pair, diffing the bodies line by line.
function diffSectionRows(baseBody, targetBody) {
  const toLineTokens = (text) => text.split("\n").map((line) => line + "\n");
  return alignDiffRows(lcsDiff(toLineTokens(baseBody), toLineTokens(targetBody)));
}

const COMPARE_CONDITION_KEYS = [
  { key: "search_enabled", label: () => t("condSearch"), format: (v) => (v ? t("on") : t("off")) },
  {
    key: "citations_enabled",
    label: () => t("condCitations"),
    format: (v) => (v === false ? t("off") : t("on")),
  },
  {
    key: "citation_style",
    label: () => t("citationStyle"),
    format: (v) => (v === "author_date" ? t("citationAuthorDate") : t("citationNumeric")),
  },
  { key: "reference_count", label: () => t("condRefs"), format: (v) => String(v ?? 0) },
  { key: "model", label: () => t("condModel"), format: (v) => (v ? String(v) : "—") },
  {
    key: "target_length",
    label: () => t("condLength"),
    format: (v) => (v ? String(v) : t("targetLengthAuto")),
  },
  {
    key: "document_type",
    label: () => t("condDocType"),
    format: (v) => (v ? String(v) : t("autoDetect")),
  },
];

// Lists the generation-condition keys whose formatted value changed between the
// two drafts. Skipped entirely when neither draft stored any conditions.
function compareConditionRows(fromConditions, toConditions) {
  if (!fromConditions && !toConditions) return [];
  const from = fromConditions || {};
  const to = toConditions || {};
  const rows = [];
  for (const spec of COMPARE_CONDITION_KEYS) {
    const fromValue = spec.format(from[spec.key]);
    const toValue = spec.format(to[spec.key]);
    if (fromValue !== toValue) {
      rows.push({ label: spec.label(), from: fromValue, to: toValue });
    }
  }
  return rows;
}

// One grid cell: same parts as text nodes, del/ins parts wrapped so only the
// relevant side highlights. An empty cell is dimmed to signal "no counterpart".
function buildCompareCell(parts) {
  const cell = document.createElement("div");
  cell.className = "compare-cell";
  if (!parts || parts.length === 0) {
    cell.classList.add("empty");
    return cell;
  }
  for (const part of parts) {
    if (part.type === "same") {
      cell.append(document.createTextNode(part.text));
    } else if (part.type === "del") {
      const del = document.createElement("del");
      del.textContent = part.text;
      cell.append(del);
    } else {
      const ins = document.createElement("ins");
      ins.textContent = part.text;
      cell.append(ins);
    }
  }
  return cell;
}

// A section block: status badge + heading, a muted v{from}/v{to} column header,
// then the aligned rows laid out as a two-column grid.
function buildCompareGridBlock(status, heading, rows, fromVersion, toVersion) {
  const details = document.createElement("details");
  details.className = "compare-section";
  details.open = true;

  const summary = document.createElement("summary");
  const badge = document.createElement("span");
  badge.className = `diff-badge ${status}`;
  badge.textContent =
    status === "added" ? t("diffAdded") : status === "removed" ? t("diffRemoved") : t("diffChanged");
  const label = document.createElement("span");
  label.className = "compare-section-title";
  label.textContent = heading || "…";
  summary.append(badge, label);
  details.append(summary);

  const grid = document.createElement("div");
  grid.className = "compare-grid";
  const headLeft = document.createElement("div");
  headLeft.className = "compare-col-head";
  headLeft.textContent = `v${fromVersion}`;
  const headRight = document.createElement("div");
  headRight.className = "compare-col-head";
  headRight.textContent = `v${toVersion}`;
  grid.append(headLeft, headRight);

  for (const row of rows) {
    grid.append(buildCompareCell(row.left), buildCompareCell(row.right));
  }
  details.append(grid);
  return details;
}

// Renders the side-by-side-ish diff of two drafts into the preview pane. Only
// createElement/textContent is used so document text is never treated as HTML.
function renderCompareView(from, to) {
  const container = els.draftPreview;
  container.replaceChildren();

  const banner = document.createElement("div");
  banner.className = "compare-banner";
  const bannerTitle = document.createElement("span");
  bannerTitle.className = "compare-banner-title";
  bannerTitle.textContent = t("compareTitle", { from: from.version, to: to.version });
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "secondary";
  closeBtn.textContent = t("compareClose");
  closeBtn.addEventListener("click", () => {
    state.compareSelection = [];
    renderDraftPreview();
  });
  banner.append(bannerTitle, closeBtn);
  container.append(banner);

  const fromSections = splitMarkdownSections(artifactBodyText(from));
  const toSections = splitMarkdownSections(artifactBodyText(to));
  const { pairs, removed, added } = matchSections(fromSections, toSections);
  const condRows = compareConditionRows(from.content?.conditions, to.content?.conditions);

  const changedCount = pairs.filter((pair) => pair.base.body !== pair.target.body).length;
  if (
    changedCount === 0 &&
    added.length === 0 &&
    removed.length === 0 &&
    condRows.length === 0
  ) {
    const message = document.createElement("p");
    message.className = "compare-summary";
    message.textContent = t("compareNoChanges");
    container.append(message);
    return;
  }

  const summary = document.createElement("p");
  summary.className = "compare-summary";
  summary.textContent = t("compareSummary", {
    changed: changedCount,
    added: added.length,
    removed: removed.length,
  });
  container.append(summary);

  if (condRows.length) {
    const wrap = document.createElement("div");
    wrap.className = "compare-conditions";
    const heading = document.createElement("p");
    heading.className = "compare-conditions-title";
    heading.textContent = t("compareConditions");
    const list = document.createElement("ul");
    for (const row of condRows) {
      const li = document.createElement("li");
      li.textContent = `${row.label}: ${row.from} → ${row.to}`;
      list.append(li);
    }
    wrap.append(heading, list);
    container.append(wrap);
  }

  // Merge-walk in target order, splicing removed sections in at their base
  // position so the reader still sees where a dropped section used to sit.
  const pairByBase = new Map(pairs.map((pair) => [pair.base, pair]));
  const pairByTarget = new Map(pairs.map((pair) => [pair.target, pair]));
  const baseIndexOf = new Map(fromSections.map((section, index) => [section, index]));
  const emittedBase = new Set();
  const unchangedTitles = [];
  let baseCursor = 0;

  const emitRemoved = (section) => {
    if (emittedBase.has(section) || pairByBase.get(section)) return;
    emittedBase.add(section);
    container.append(
      buildCompareGridBlock(
        "removed",
        section.heading,
        [{ kind: "del", left: [{ type: "del", text: section.body }], right: [] }],
        from.version,
        to.version,
      ),
    );
  };

  for (const target of toSections) {
    const pair = pairByTarget.get(target);
    if (!pair) {
      container.append(
        buildCompareGridBlock(
          "added",
          target.heading,
          [{ kind: "ins", left: [], right: [{ type: "ins", text: target.body }] }],
          from.version,
          to.version,
        ),
      );
      continue;
    }
    const partnerIndex = baseIndexOf.get(pair.base);
    while (baseCursor < partnerIndex) {
      emitRemoved(fromSections[baseCursor]);
      baseCursor++;
    }
    if (baseCursor === partnerIndex) baseCursor++;
    emittedBase.add(pair.base);
    if (pair.base.body === pair.target.body) {
      unchangedTitles.push(pair.target.heading || "…");
    } else {
      container.append(
        buildCompareGridBlock(
          "changed",
          pair.target.heading,
          diffSectionRows(pair.base.body, pair.target.body),
          from.version,
          to.version,
        ),
      );
    }
  }
  for (const section of fromSections) emitRemoved(section);

  if (unchangedTitles.length) {
    const details = document.createElement("details");
    details.className = "compare-section compare-unchanged";
    const summaryEl = document.createElement("summary");
    summaryEl.textContent = t("diffUnchanged", { count: unchangedTitles.length });
    details.append(summaryEl);
    const list = document.createElement("ul");
    for (const titleText of unchangedTitles) {
      const li = document.createElement("li");
      li.textContent = titleText;
      list.append(li);
    }
    details.append(list);
    container.append(details);
  }
}

let mermaidReady = false;

function renderMermaidDiagrams() {
  const nodes = [...els.draftPreview.querySelectorAll(".mermaid")];
  if (nodes.length === 0 || !window.mermaid) return;
  if (!mermaidReady) {
    window.mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      suppressErrorRendering: true,
    });
    mermaidReady = true;
  }
  // Mermaid clears a node it fails to parse, so keep the source for fallback.
  for (const node of nodes) {
    node.dataset.source = node.textContent;
  }
  window.mermaid.run({ nodes }).catch(() => {
    // Invalid diagram source: show it as a plain code block instead.
    for (const node of els.draftPreview.querySelectorAll(".mermaid")) {
      if (node.querySelector("svg")) continue;
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = node.dataset.source || node.textContent;
      pre.append(code);
      node.replaceWith(pre);
    }
  });
}

function renderMathExpressions() {
  if (!window.katex) return;
  for (const node of els.draftPreview.querySelectorAll(".math-inline")) {
    renderMathNode(node, false);
  }
  for (const node of els.draftPreview.querySelectorAll(".math-block")) {
    renderMathNode(node, true);
  }
}

function renderMathNode(node, displayMode) {
  const source = node.textContent || "";
  try {
    window.katex.render(source, node, { throwOnError: false, displayMode });
  } catch {
    node.textContent = source;
  }
}

function normalizeSectionHeadingText(value) {
  return String(value || "")
    .replace(/^\d+(?:\.\d+)*\s+/, "")
    .trim()
    .replace(/\s+/g, " ");
}

// Maps each section's normalized title to its id. Headings render with a
// numeric prefix ("1.2 Title") only for doc types with numbered_headings
// enabled (see doc_types.py); others render the bare title. Matching on the
// title instead of parsing a numeric prefix works for both.
function sectionDraftIndex() {
  const byTitle = new Map();
  for (const artifact of state.artifacts) {
    if (artifact.type !== "section_draft") continue;
    const section = artifact.content?.section;
    const id = section?.id;
    const title = section?.title;
    if (!id || !title) continue;
    byTitle.set(normalizeSectionHeadingText(title), String(id));
  }
  return byTitle;
}

function attachSectionFeedbackButtons() {
  const byTitle = sectionDraftIndex();
  for (const heading of els.draftPreview.querySelectorAll("h2, h3, h4, h5, h6")) {
    const numericId = heading.textContent.trim().match(/^(\d+(?:\.\d+)+)\s+/)?.[1];
    const sectionId =
      numericId || byTitle.get(normalizeSectionHeadingText(heading.textContent));
    if (!sectionId) continue;
    heading.dataset.sectionId = sectionId;
    // Feedback needs a stored section artifact; navigation only needs the
    // deterministic numeric heading id and remains available for stale drafts.
    if (byTitle.size === 0 && numericId) continue;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "section-feedback-button";
    button.title = t("feedbackPanelTitle", { id: sectionId });
    button.textContent = "💬";
    button.addEventListener("click", () => toggleSectionFeedbackPanel(sectionId, heading));
    heading.append(button);
  }
}

function renderFeedbackHistory(container, items) {
  container.innerHTML = "";
  if (!items.length) {
    container.innerHTML = `<p class="item-meta">${escapeHtml(t("noFeedback"))}</p>`;
    return;
  }
  for (const item of items) {
    const entry = document.createElement("article");
    entry.className = "feedback-entry";
    entry.innerHTML = `
      <div class="feedback-entry-meta">
        <span class="feedback-badge"></span>
        <span class="feedback-time"></span>
      </div>
      <p class="feedback-text"></p>
    `;
    const badge = entry.querySelector(".feedback-badge");
    badge.textContent = item.applied ? t("feedbackApplied") : t("feedbackPending");
    badge.classList.add(item.applied ? "applied" : "pending");
    entry.querySelector(".feedback-time").textContent = formatDate(item.created_at);
    entry.querySelector(".feedback-text").textContent = item.answer;
    container.append(entry);
  }
}

async function toggleSectionFeedbackPanel(sectionId, heading, initialComment = "") {
  const project = selectedProject();
  if (!project) return;

  const wasOpen = els.draftPreview.querySelector(
    `.section-feedback-panel[data-section-id="${sectionId}"]`,
  );
  if (wasOpen && initialComment) {
    const textarea = wasOpen.querySelector("textarea");
    textarea.value = initialComment;
    textarea.focus();
    return wasOpen;
  }
  for (const panel of els.draftPreview.querySelectorAll(".section-feedback-panel")) {
    panel.remove();
  }
  if (wasOpen) return null;

  const panel = document.createElement("div");
  panel.className = "section-feedback-panel";
  panel.dataset.sectionId = sectionId;
  panel.innerHTML = `
    <p class="feedback-panel-title"></p>
    <div class="feedback-history"></div>
    <textarea rows="3" placeholder="${escapeHtml(t("feedbackPlaceholder"))}"></textarea>
    <div class="answer-batch-actions">
      <button type="button" class="feedback-save">${escapeHtml(t("saveComment"))}</button>
      <button type="button" class="feedback-save-run">${escapeHtml(t("saveAndImproveSection"))}</button>
      <button type="button" class="secondary feedback-close">${escapeHtml(t("close"))}</button>
    </div>
  `;
  panel.querySelector(".feedback-panel-title").textContent = t("feedbackPanelTitle", {
    id: sectionId,
  });
  heading.insertAdjacentElement("afterend", panel);

  const history = panel.querySelector(".feedback-history");
  const feedbackUrl = `/projects/${project.id}/sections/${encodeURIComponent(sectionId)}/feedback`;
  const loadHistory = async () => {
    try {
      renderFeedbackHistory(history, await api(feedbackUrl));
    } catch (error) {
      history.innerHTML = `<p class="item-meta">${escapeHtml(error.message)}</p>`;
    }
  };
  await loadHistory();

  const textarea = panel.querySelector("textarea");
  textarea.value = initialComment;
  const saveButtons = [
    panel.querySelector(".feedback-save"),
    panel.querySelector(".feedback-save-run"),
  ];
  const saveFeedback = async (startImprovement = false) => {
    const comment = textarea.value.trim();
    if (!comment) return;
    for (const button of saveButtons) button.disabled = true;
    try {
      await api(feedbackUrl, {
        method: "POST",
        body: JSON.stringify({ comment }),
      });
      textarea.value = "";
      if (startImprovement) {
        setRunButtonRunning(true);
        resetProgressForRun("feedback_revision");
        const result = await api(`/projects/${project.id}/run`, {
          method: "POST",
          body: JSON.stringify({ force_from: "feedback_revision" }),
        });
        panel.remove();
        showToast(
          result.message || t("sectionImprovementStarted", { id: sectionId }),
        );
        startRunPolling();
      } else {
        showToast(t("feedbackSaved", { id: sectionId }));
        await loadHistory();
      }
    } catch (error) {
      if (startImprovement) {
        stopRunPolling();
        setRunButtonRunning(false);
        await loadProgress().catch(() => {});
      }
      showToast(error.message, true);
    } finally {
      for (const button of saveButtons) button.disabled = false;
    }
  };
  panel.querySelector(".feedback-save").addEventListener("click", () => saveFeedback(false));
  panel.querySelector(".feedback-save-run").addEventListener("click", () => saveFeedback(true));
  panel.querySelector(".feedback-close").addEventListener("click", () => panel.remove());
  textarea.focus();
  return panel;
}

function layoutPhase() {
  const project = selectedProject();
  if (!project) return null;
  if (project.status === "running" || state.progress?.status === "running") return "running";
  if (state.questions.some((q) => q.status === "pending")) return "questions";
  if (project.status === "failed" || project.status === "cancelled") return "attention";
  if (latestDraft()) return "review";
  return "setup";
}

function applyLayoutPhase() {
  const project = selectedProject();
  const phase = layoutPhase();
  if (!project || !phase) return;
  els.projectDetail.dataset.phase = phase;
  const key = `${project.id}:${phase}`;
  // Apply the phase's default open/collapsed state only when the phase actually
  // changes, so a user's manual toggle survives re-renders until the next phase.
  if (state.appliedPhase === key) return;
  state.appliedPhase = key;
  els.requestDetails.open = phase === "setup";
  els.pipelinePanel.open = phase === "running" || phase === "attention";
}

// The status pill sits right above the message in the compact box, so drop
// the message when it would just repeat the pill (e.g. "review needed" twice).
function setStripMessage(message) {
  const pillText = (els.detailStatus.textContent || "").trim().toLowerCase();
  const text = (message || "").trim();
  els.stripMessage.textContent = text;
  els.stripMessage.classList.toggle("hidden", !text || text.toLowerCase() === pillText);
}

function renderStatusStrip() {
  const project = selectedProject();
  if (!project) return;

  const phase = layoutPhase();
  let message = "";
  if (phase === "questions") {
    const pendingCount = state.questions.filter((question) => question.status === "pending").length;
    message =
      state.language === "ko"
        ? `${pendingCount}개 질문에 답변`
        : `Answer ${pendingCount} question${pendingCount === 1 ? "" : "s"}`;
  } else if (phase === "running") {
    const runningStep = state.progress?.steps?.find((step) => step.status === "running");
    message = runningStep
      ? phaseLabel(runningStep.phase, runningStep.label)
      : t("writingInProgress");
  } else if (phase === "attention") {
    message = project.status === "cancelled" ? t("runCancelled") : t("pipelineFailed");
  } else if (phase === "review") {
    // Match renderQuality's pill text, or the two flip-flop between paints.
    const needsReview =
      project.status === "review_needed" || state.quality?.status === "review_needed";
    message = needsReview ? t("qualityReviewNeeded") : t("reviewDraft");
  } else {
    message = t("startWritingAction");
  }
  setStripMessage(message);

  const showProgress = phase === "running" && Boolean(state.progress);
  els.stripProgress.classList.toggle("hidden", !showProgress);
  if (showProgress) {
    els.stripFill.style.width = `${state.progress.percent}%`;
    els.stripPercent.textContent = `${state.progress.percent}%`;
  }
}

function renderNextAction() {
  const project = selectedProject();
  if (!project) return;

  renderStatusStrip();

  const pendingCount = state.questions.filter((question) => question.status === "pending").length;
  els.nextAction.className = "next-action";
  els.nextActionItems.innerHTML = "";
  els.nextActionItems.classList.add("hidden");

  if (pendingCount === 0) {
    els.nextAction.classList.add("hidden");
    return;
  }

  els.nextAction.classList.add("needs-answer");
  els.nextActionTitle.textContent =
    state.language === "ko"
      ? `${pendingCount}개 질문에 답변`
      : `Answer ${pendingCount} question${pendingCount === 1 ? "" : "s"}`;
  els.nextActionBody.textContent = t("writerNeedsInput");
  els.nextActionItems.classList.remove("hidden");
  const form = document.createElement("form");
  form.className = "quick-answer-form";
  for (const question of state.questions.filter((item) => item.status === "pending")) {
    const item = document.createElement("div");
    item.className = "quick-question";
    const questionText =
      typeof question.question.question === "string"
        ? question.question.question
        : JSON.stringify(question.question);
    item.innerHTML = `
      <p></p>
      <input aria-label="${escapeHtml(t("answer"))}" placeholder="${escapeHtml(t("answer"))}" />
    `;
    item.querySelector("p").textContent = questionText;
    const input = item.querySelector("input");
    input.value = getAnswerDraft(question.id);
    input.addEventListener("input", () => {
      setAnswerDraft(question.id, input.value);
    });
    form.append(item);
  }
  const actions = document.createElement("div");
  actions.className = "answer-batch-actions";
  actions.innerHTML = `
    <button type="submit">${escapeHtml(t("saveAnswersAndRun"))}</button>
    <button type="button" class="secondary save-only">${escapeHtml(t("saveAllAnswers"))}</button>
  `;
  actions.querySelector(".save-only").addEventListener("click", async () => {
    await saveAllAnswers();
  });
  form.append(actions);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await saveAllAnswers({ startRun: true });
  });
  els.nextActionItems.append(form);
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
  populateDocTypeSelects();
  updateDocumentTitle();
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
  renderQuality();
  renderNextAction();
  renderProjectSettings();
  renderTabs();
  if (selectedProject()) {
    applyLayoutPhase();
  }
}

function toggleHidden(element) {
  element.classList.toggle("hidden");
}

els.languageSelect?.addEventListener("change", () => {
  state.language = els.languageSelect.value === "ko" ? "ko" : "en";
  localStorage.setItem("docugenLanguage", state.language);
  rerenderCurrentView();
  loadHealth().catch(() => {});
});

els.themeSelect?.addEventListener("change", () => {
  const value = els.themeSelect.value;
  state.theme = ["pastel", "simpsons", "newspaper"].includes(value) ? value : "pastel";
  localStorage.setItem("docugenTheme", state.theme);
  applyTheme();
});

els.sidebarToggle?.addEventListener("click", toggleSidebar);
els.sidebarBackdrop?.addEventListener("click", () => setSidebarCollapsed(true, { persist: false }));

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
  state.compareSelection = [];
  state.draftView = state.draftView === "rendered" ? "raw" : "rendered";
  renderDraftPreview();
});

els.qualityToggle?.addEventListener("click", () => {
  state.qualityOpen = !state.qualityOpen;
  localStorage.setItem("docugenQualityPanel", state.qualityOpen ? "open" : "collapsed");
  renderQuality();
});

els.qualityClose?.addEventListener("click", () => {
  state.qualityOpen = false;
  localStorage.setItem("docugenQualityPanel", "collapsed");
  renderQuality();
});

els.detailStatus?.addEventListener("click", () => {
  if (els.detailStatus.disabled) return;
  state.qualityOpen = !state.qualityOpen;
  localStorage.setItem("docugenQualityPanel", state.qualityOpen ? "open" : "collapsed");
  renderQuality();
  if (state.qualityOpen) {
    els.qualityPanel?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
});

els.versionsButton?.addEventListener("click", () => {
  state.versionsOpen = !state.versionsOpen;
  renderVersions();
  updateVersionsVisibility();
});

els.formViewButton?.addEventListener("click", () => {
  const project = selectedProject();
  if (!project) return;
  if (!latestDraft()) {
    showToast(t("noDraft"), true);
    return;
  }
  window.open(formViewUrl(project.id), "_blank", "noopener,noreferrer");
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

async function startWritingRun() {
  const project = selectedProject();
  if (!project) return;

  // "Improve draft" mode: without force_from every cached stage is reused and
  // the run is a no-op, so force the review/revision tail to actually re-run.
  const improveMode = Boolean(
    latestDraft() &&
      (project.status === "review_needed" || state.quality?.status === "review_needed"),
  );
  const startPhase = improveMode ? "continuity_review" : "intake";

  setRunButtonRunning(true);
  resetProgressForRun(startPhase);

  try {
    const result = await api(`/projects/${project.id}/run`, {
      method: "POST",
      body: JSON.stringify(improveMode ? { force_from: startPhase } : {}),
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
}

els.runButton.addEventListener("click", startWritingRun);
els.cancelButton?.addEventListener("click", cancelWritingRun);

els.deleteProjectButton.addEventListener("click", async () => {
  const project = selectedProject();
  if (!project) return;
  await deleteProject(project);
});

function openRequestEdit() {
  const project = selectedProject();
  if (!project) return;
  els.editProjectTitle.value = project.title;
  els.editProjectRequest.value = project.initial_request;
  els.requestView.classList.add("hidden");
  els.requestEditForm.classList.remove("hidden");
}

function closeRequestEdit() {
  els.requestEditForm.classList.add("hidden");
  els.requestView.classList.remove("hidden");
}

els.editRequestButton?.addEventListener("click", openRequestEdit);
els.cancelRequestEdit?.addEventListener("click", closeRequestEdit);

els.requestEditForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const project = selectedProject();
  if (!project) return;
  try {
    await api(`/projects/${project.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        title: els.editProjectTitle.value.trim(),
        initial_request: els.editProjectRequest.value.trim(),
      }),
    });
    closeRequestEdit();
    showToast(t("requestUpdated"));
    await loadProjects();
  } catch (error) {
    showToast(error.message, true);
  }
});

els.addReferenceUrlButton?.addEventListener("click", async () => {
  const project = selectedProject();
  if (!project) return;
  const url = els.addReferenceUrl.value.trim();
  if (!url) {
    showToast(t("enterUrl"), true);
    return;
  }
  try {
    await api(`/projects/${project.id}/references/urls`, {
      method: "POST",
      body: JSON.stringify({ urls: [url] }),
    });
    els.addReferenceUrl.value = "";
    showToast(t("referenceAdded"));
    await loadReferences();
  } catch (error) {
    showToast(error.message, true);
  }
});

els.addReferenceFilesButton?.addEventListener("click", async () => {
  const project = selectedProject();
  if (!project) return;
  const files = Array.from(els.addReferenceFiles.files || []);
  if (!files.length) {
    showToast(t("selectFiles"), true);
    return;
  }
  const formData = new FormData();
  for (const file of files) formData.append("files", file);
  try {
    await api(`/projects/${project.id}/references/files`, {
      method: "POST",
      body: formData,
    });
    els.addReferenceFiles.value = "";
    showToast(t("referenceAdded"));
    await loadReferences();
  } catch (error) {
    showToast(error.message, true);
  }
});

els.addStyleFilesButton?.addEventListener("click", async () => {
  const project = selectedProject();
  if (!project) return;
  const files = Array.from(els.addStyleFiles.files || []);
  if (!files.length) {
    showToast(t("selectFiles"), true);
    return;
  }
  const formData = new FormData();
  for (const file of files) formData.append("files", file);
  try {
    await api(`/projects/${project.id}/references/files?kind=style`, {
      method: "POST",
      body: formData,
    });
    els.addStyleFiles.value = "";
    showToast(t("referenceAdded"));
    await loadReferences();
  } catch (error) {
    showToast(error.message, true);
  }
});

els.searchEnabledSelect?.addEventListener("change", saveProjectSettings);
els.sectionSearchSelect?.addEventListener("change", saveProjectSettings);
els.searchEngine1Select?.addEventListener("change", saveProjectSettings);
els.searchEngine2Select?.addEventListener("change", saveProjectSettings);
els.searchEngine3Select?.addEventListener("change", saveProjectSettings);
els.searchHeadlessSelect?.addEventListener("change", saveProjectSettings);
els.searchStealthSelect?.addEventListener("change", saveProjectSettings);
els.searchLocaleSelect?.addEventListener("change", saveProjectSettings);
els.searchQueryLanguageSelect?.addEventListener("change", saveProjectSettings);
els.citationStyleSelect?.addEventListener("change", saveProjectSettings);
els.targetLengthInput?.addEventListener("change", saveProjectSettings);
els.docTypeSelect?.addEventListener("change", saveDocType);

els.projectForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const referenceUrls = els.projectReferenceUrls.value
    .split("\n")
    .map((url) => url.trim())
    .filter(Boolean);
  const referenceFiles = Array.from(els.projectReferenceFiles.files || []);

  try {
    const docType = els.projectDocType?.value || "auto";
    const project = await api("/projects", {
      method: "POST",
      body: JSON.stringify({
        title: els.projectTitle.value,
        initial_request: els.projectRequest.value,
        document_type: docType === "auto" ? null : docType,
      }),
    });
    state.selectedProjectId = project.id;
    state.selectedStepPhase = null;
    // Sync the URL now, or loadProjects() re-selects the previous project
    // from the stale ?project= param.
    syncProjectInUrl(project.id);

    const referenceErrors = [];
    if (referenceUrls.length) {
      try {
        await api(`/projects/${project.id}/references/urls`, {
          method: "POST",
          body: JSON.stringify({ urls: referenceUrls }),
        });
      } catch (error) {
        referenceErrors.push(error.message);
      }
    }
    if (referenceFiles.length) {
      const formData = new FormData();
      for (const file of referenceFiles) formData.append("files", file);
      try {
        await api(`/projects/${project.id}/references/files`, {
          method: "POST",
          body: formData,
        });
      } catch (error) {
        referenceErrors.push(error.message);
      }
    }

    els.projectForm.reset();
    els.projectForm.classList.add("hidden");
    closeSidebarOnNarrow();
    if (referenceErrors.length) {
      showToast(t("referencesFailed", { errors: referenceErrors.join(" / ") }), true);
    } else {
      showToast(t("projectCreated"));
    }
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

function currentLlmProviderMeta() {
  const id = els.llmProvider.value;
  return llmSettingsState.providers.find((preset) => preset.id === id) || null;
}

function providerLabel(preset) {
  return state.language === "ko" ? preset.label_ko : preset.label_en;
}

function providerNote(preset) {
  return state.language === "ko" ? preset.note_ko : preset.note_en;
}

function populateLlmProviderSelect() {
  els.llmProvider.innerHTML = "";
  for (const preset of llmSettingsState.providers) {
    const option = document.createElement("option");
    option.value = preset.id;
    option.textContent = providerLabel(preset);
    els.llmProvider.append(option);
  }
}

function renderLlmProviderFields() {
  const preset = currentLlmProviderMeta();
  if (!preset) return;
  els.llmBaseUrlRow.classList.toggle("hidden", !preset.base_url_editable);
  els.llmApiKeyRow.classList.toggle("hidden", !preset.needs_api_key);
  els.llmModelRow.classList.toggle("hidden", !preset.model_editable);
  els.llmProviderNote.textContent = providerNote(preset);
  els.llmTestResult.classList.add("hidden");
}

function fillLlmFormForProvider(providerId) {
  const preset = llmSettingsState.providers.find((item) => item.id === providerId);
  if (!preset) return;
  const active = llmSettingsState.active;
  const isActive = active && active.provider === providerId;
  els.llmProvider.value = providerId;
  els.llmBaseUrl.value = isActive ? active.base_url : preset.base_url;
  els.llmModel.value = isActive ? active.model : preset.default_model;
  els.llmApiKey.value = "";
  els.llmApiKey.placeholder =
    isActive && active.has_api_key ? active.api_key_masked : "sk-...";
  renderLlmProviderFields();
}

async function loadLlmSettings() {
  const data = await api("/settings/llm");
  llmSettingsState.providers = data.providers || [];
  llmSettingsState.active = data.active || null;
  llmSettingsState.loaded = true;
  populateLlmProviderSelect();
  fillLlmFormForProvider(
    llmSettingsState.active?.provider || llmSettingsState.providers[0]?.id,
  );
}

function collectLlmForm() {
  const preset = currentLlmProviderMeta();
  const payload = { provider: els.llmProvider.value };
  if (preset?.base_url_editable) payload.base_url = els.llmBaseUrl.value.trim();
  if (preset?.model_editable) payload.model = els.llmModel.value.trim();
  // Empty key on submit means "keep the stored one"; send null in that case.
  const key = els.llmApiKey.value.trim();
  payload.api_key = key ? key : null;
  return payload;
}

async function openLlmSettings() {
  try {
    if (!llmSettingsState.loaded) await loadLlmSettings();
    else fillLlmFormForProvider(llmSettingsState.active?.provider);
    if (!imageSettingsState.loaded) await loadImageSettings();
    else fillImageFormForProvider(imageSettingsState.active?.provider);
    els.llmTestResult.classList.add("hidden");
    els.imageTestResult.classList.add("hidden");
    els.llmSettingsModal.showModal();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function saveLlmSettings() {
  try {
    const data = await api("/settings/llm", {
      method: "PUT",
      body: JSON.stringify(collectLlmForm()),
    });
    llmSettingsState.active = data.active;
    showToast(t("llmSaved"));
    els.llmSettingsModal.close();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function testLlmSettings() {
  els.llmTestButton.disabled = true;
  els.llmTestResult.classList.remove("hidden");
  els.llmTestResult.classList.remove("ok", "error");
  els.llmTestResult.textContent = t("llmTesting");
  try {
    const result = await api("/settings/llm/test", {
      method: "POST",
      body: JSON.stringify(collectLlmForm()),
    });
    if (result.ok) {
      els.llmTestResult.classList.add("ok");
      els.llmTestResult.textContent = t("llmTestOk", { model: result.model });
    } else {
      els.llmTestResult.classList.add("error");
      els.llmTestResult.textContent = t("llmTestFail", { error: result.error || "" });
    }
  } catch (error) {
    els.llmTestResult.classList.add("error");
    els.llmTestResult.textContent = t("llmTestFail", { error: error.message });
  } finally {
    els.llmTestButton.disabled = false;
  }
}

function currentImageProviderMeta() {
  const id = els.imageProvider.value;
  return imageSettingsState.providers.find((preset) => preset.id === id) || null;
}

function populateImageProviderSelect() {
  els.imageProvider.innerHTML = "";
  for (const preset of imageSettingsState.providers) {
    const option = document.createElement("option");
    option.value = preset.id;
    option.textContent = providerLabel(preset);
    els.imageProvider.append(option);
  }
}

function renderImageProviderFields() {
  const preset = currentImageProviderMeta();
  if (!preset) return;
  els.imageBaseUrlRow.classList.toggle("hidden", !preset.base_url_editable);
  els.imageApiKeyRow.classList.toggle("hidden", !preset.needs_api_key);
  els.imageModelRow.classList.toggle("hidden", !preset.model_editable);
  els.imageOptionsRows.classList.toggle("hidden", preset.id === "disabled");
  els.imageProviderNote.textContent = providerNote(preset);
  els.imageTestResult.classList.add("hidden");
}

function fillImageFormForProvider(providerId) {
  const preset = imageSettingsState.providers.find((item) => item.id === providerId);
  if (!preset) return;
  const active = imageSettingsState.active;
  const isActive = active && active.provider === providerId;
  els.imageProvider.value = providerId;
  els.imageBaseUrl.value = isActive ? active.base_url : preset.base_url;
  els.imageModel.value = isActive ? active.model : preset.default_model;
  els.imageApiKey.value = "";
  els.imageApiKey.placeholder =
    isActive && active.has_api_key ? active.api_key_masked : "sk-...";
  renderImageProviderFields();
}

function fillImageOptions() {
  const options = imageSettingsState.options;
  if (!options) return;
  els.imageMainToggle.checked = Boolean(options.main_image);
  els.imageSectionToggle.checked = Boolean(options.section_images);
  els.imageMaxCount.value = options.max_images;
  els.imageStyle.value = options.style;
}

async function loadImageSettings() {
  const data = await api("/settings/image");
  imageSettingsState.providers = data.providers || [];
  imageSettingsState.active = data.active || null;
  imageSettingsState.options = data.options || null;
  imageSettingsState.loaded = true;
  populateImageProviderSelect();
  fillImageFormForProvider(
    imageSettingsState.active?.provider || imageSettingsState.providers[0]?.id,
  );
  fillImageOptions();
}

function collectImageForm() {
  const preset = currentImageProviderMeta();
  const payload = { provider: els.imageProvider.value };
  if (preset?.base_url_editable) payload.base_url = els.imageBaseUrl.value.trim();
  if (preset?.model_editable) payload.model = els.imageModel.value.trim();
  const key = els.imageApiKey.value.trim();
  payload.api_key = key ? key : null;
  let maxImages = Number.parseInt(els.imageMaxCount.value, 10);
  if (Number.isNaN(maxImages)) maxImages = 5;
  maxImages = Math.max(0, Math.min(20, maxImages));
  payload.options = {
    main_image: els.imageMainToggle.checked,
    section_images: els.imageSectionToggle.checked,
    max_images: maxImages,
    style: els.imageStyle.value,
  };
  return payload;
}

async function saveImageSettings() {
  try {
    const data = await api("/settings/image", {
      method: "PUT",
      body: JSON.stringify(collectImageForm()),
    });
    imageSettingsState.active = data.active;
    showToast(t("imageSaved"));
    els.llmSettingsModal.close();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function testImageSettings() {
  els.imageTestButton.disabled = true;
  els.imageTestResult.classList.remove("hidden");
  els.imageTestResult.classList.remove("ok", "error");
  els.imageTestResult.textContent = t("llmTesting");
  try {
    const result = await api("/settings/image/test", {
      method: "POST",
      body: JSON.stringify(collectImageForm()),
    });
    if (result.ok) {
      els.imageTestResult.classList.add("ok");
      els.imageTestResult.textContent = t("llmTestOk", { model: result.model });
    } else {
      els.imageTestResult.classList.add("error");
      els.imageTestResult.textContent = t("llmTestFail", { error: result.error || "" });
    }
  } catch (error) {
    els.imageTestResult.classList.add("error");
    els.imageTestResult.textContent = t("llmTestFail", { error: error.message });
  } finally {
    els.imageTestButton.disabled = false;
  }
}

els.llmSettingsButton?.addEventListener("click", openLlmSettings);
els.llmSettingsClose?.addEventListener("click", () => els.llmSettingsModal.close());
els.llmProvider?.addEventListener("change", () =>
  fillLlmFormForProvider(els.llmProvider.value),
);
els.llmTestButton?.addEventListener("click", testLlmSettings);
els.llmSaveButton?.addEventListener("click", saveLlmSettings);
els.imageProvider?.addEventListener("change", () =>
  fillImageFormForProvider(els.imageProvider.value),
);
els.imageTestButton?.addEventListener("click", testImageSettings);
els.imageSaveButton?.addEventListener("click", saveImageSettings);

async function boot() {
  if (!translations[state.language]) {
    state.language = "en";
  }
  applyTheme();
  applySidebar();
  applyStaticTranslations();
  try {
    await loadHealth();
    await loadDocTypes();
    await loadProjects();
  } catch (error) {
    showToast(error.message, true);
  }
}

boot();
