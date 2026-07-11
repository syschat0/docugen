"""Document type profiles: per-genre defaults and prompt guidance.

A profile declares how one kind of document is planned, written, and
rendered. The pipeline stays identical across types; profiles only change
prompt guidance and a few rendering/search defaults, so adding a type is a
data change, not a code change.

Profile fields:
- label_en / label_ko: UI labels.
- research_default: whether web research makes sense for this genre. An
  explicit per-project search setting still wins; the env SEARCH_ENABLED
  gate still applies (a profile cannot re-enable globally disabled search).
- citations_enabled: whether inline citation markers and the Sources
  section belong in the final document.
- intake_priorities: ordered missing-information checks for the intake agent.
  These are guidance, not questions that must all be asked.
- numbered_headings: whether section headings carry "1.2"-style numbers.
- default_section_length: target body characters per section.
- style_hint: default sentence register, used when the user's request does
  not imply one.
- brief_guidance / outline_guidance / section_guidance: genre conventions
  injected into the corresponding pipeline prompts.
- classify_hint: one-line description for the intake type classifier.
"""

from typing import Any, Dict

DEFAULT_DOC_TYPE = "report"

DOC_TYPES: Dict[str, Dict[str, Any]] = {
    "report": {
        "rubric": [
            {"key": "accuracy", "name": "Accuracy & evidence",
             "description": "claims are specific, correct, and supported by the cited sources"},
            {"key": "structure", "name": "Structural clarity",
             "description": "each section owns one topic; the reader can navigate to answers fast"},
            {"key": "actionability", "name": "Actionability",
             "description": "findings lead to clear conclusions or next steps, not vague statements"},
            {"key": "completeness", "name": "Completeness",
             "description": "the brief's must-include topics are all covered at adequate depth"},
        ],
        "label_en": "Report / Brief",
        "label_ko": "보고서·브리프",
        "research_default": True,
        "citations_enabled": True,
        "intake_priorities": [
            "The reader and the decision or action this report should support.",
            "Scope boundaries, comparison targets, and relevant time period.",
            "Required facts, metrics, organizations, or supplied evidence.",
            "Desired length, delivery format, and deadline if they constrain depth.",
        ],
        "numbered_headings": True,
        "default_section_length": 500,
        "classify_hint": (
            "structured informational report: status report, market research, "
            "analysis brief, policy summary"
        ),
        "style_hint": "formal expository prose (Korean: -이다/한다체)",
        "brief_guidance": (
            "A report informs a decision or captures the state of a topic. "
            "Name the reader's decision or question in the goal, and keep "
            "success criteria factual and checkable."
        ),
        "outline_guidance": (
            "Open with context and scope, develop the findings in the middle "
            "chapters, and close with conclusions and next steps. Group "
            "chapters by subtopic, not by source."
        ),
        "section_guidance": (
            "State findings directly and support them with the sources. "
            "Prefer concrete figures and named entities over generalities."
        ),
    },
    "academic_paper": {
        "rubric": [
            {"key": "thesis", "name": "Research question focus",
             "description": "every chapter serves the stated research question and the conclusion answers it"},
            {"key": "argument", "name": "Argumentation & evidence",
             "description": "claims follow logically and each substantive claim carries a citation"},
            {"key": "objectivity", "name": "Academic register",
             "description": "objective written register throughout; no first person or rhetorical questions"},
            {"key": "terminology", "name": "Term definitions & consistency",
             "description": "key terms are defined on first use and used identically everywhere"},
        ],
        "label_en": "Academic mini-thesis",
        "label_ko": "소논문 (학교 과제)",
        "research_default": True,
        "citations_enabled": True,
        "intake_priorities": [
            "The exact research question or thesis the paper must answer.",
            "Course, subject level, audience, and required academic format.",
            "Required sources, citation rules, or evidence restrictions.",
            "Length and any mandatory sections, methods, or comparison cases.",
        ],
        "numbered_headings": True,
        "default_section_length": 600,
        "classify_hint": (
            "school assignment research paper (소논문): a thesis-style document "
            "with a research question, prior-work review, and conclusion"
        ),
        "style_hint": "formal academic written register (Korean: -이다/한다체, 문어체)",
        "brief_guidance": (
            "An academic mini-thesis answers one explicit research question. "
            "State that question in the goal, name the intended course or "
            "subject area in the audience, and include objectivity and "
            "citation coverage in the success criteria."
        ),
        "outline_guidance": (
            "Follow the academic structure: 서론 (research background, purpose, "
            "research question), 이론적 배경 (key concepts and prior work), one "
            "or two 본론 chapters (analysis and discussion), and 결론 (summary, "
            "implications, limitations). Do not add an abstract chapter."
        ),
        "section_guidance": (
            "Keep an objective academic voice: no first person, no rhetorical "
            "questions. Define each key term on first use and support every "
            "substantive claim with a citation. Distinguish established facts "
            "from the document's own interpretation."
        ),
    },
    "blog_post": {
        "rubric": [
            {"key": "hook", "name": "Hook & momentum",
             "description": "the opening earns attention and each section keeps a reason to continue"},
            {"key": "concreteness", "name": "Concrete examples",
             "description": "ideas are shown through examples or small stories, not abstractions"},
            {"key": "voice", "name": "Consistent voice",
             "description": "one conversational persona addressing the reader directly throughout"},
            {"key": "scannability", "name": "Scannability",
             "description": "short paragraphs and curiosity-driven headings; skimming still conveys the takeaway"},
        ],
        "label_en": "Blog post / Column",
        "label_ko": "블로그·칼럼",
        "research_default": True,
        "citations_enabled": True,
        "intake_priorities": [
            "Target reader, publishing channel, and what should earn attention.",
            "The one takeaway or call to action readers should leave with.",
            "Writer persona, stance, and preferred conversational register.",
            "Desired length and concrete examples or stories that must appear.",
        ],
        "numbered_headings": False,
        "default_section_length": 350,
        "classify_hint": (
            "blog post or opinion column for online readers: personal angle, "
            "conversational, scannable"
        ),
        "style_hint": "friendly conversational prose (Korean: -이에요/해요체 or -입니다체)",
        "brief_guidance": (
            "A blog post earns attention rather than assuming it. The goal "
            "should name the takeaway a reader leaves with, and the tone "
            "should fit the writer's persona in the request."
        ),
        "outline_guidance": (
            "Open with a hook chapter that names the reader's problem or "
            "curiosity, develop 2-4 focused idea chapters, and close with a "
            "takeaway or call to action. Chapter titles should be curiosity- "
            "driven phrases, not formal labels like 'Introduction'."
        ),
        "section_guidance": (
            "Write short paragraphs (1-3 sentences) and use concrete examples "
            "or small stories. Address the reader directly. Link sources "
            "naturally in the flow instead of stacking citations."
        ),
    },
    "essay": {
        "rubric": [
            {"key": "throughline", "name": "Single through-line",
             "description": "one thesis or felt experience develops across the whole piece without detours"},
            {"key": "showing", "name": "Scenes & sensory detail",
             "description": "specific scenes and senses carry the meaning before any telling"},
            {"key": "voice", "name": "Voice consistency",
             "description": "the same first-person voice, register, and mood from first line to last"},
            {"key": "resonance", "name": "Turn & resonance",
             "description": "the piece turns somewhere and the ending lands with weight rather than summary"},
        ],
        "label_en": "Essay / Opinion piece",
        "label_ko": "에세이·논설문",
        "research_default": False,
        "citations_enabled": False,
        "intake_priorities": [
            "The single thesis, experience, or emotional through-line.",
            "Intended reader and the occasion or reason for writing.",
            "Point of view, mood, and how personal or argumentative it should be.",
            "Scenes, images, arguments, or ending effect that must be included.",
        ],
        "numbered_headings": False,
        "default_section_length": 450,
        "classify_hint": (
            "personal essay or opinion piece (에세이, 수필, 논설문): "
            "thesis-driven or reflective prose in the writer's own voice"
        ),
        "style_hint": "literary first-person prose matching the request's mood",
        "brief_guidance": (
            "An essay develops one thesis or one felt experience. Put that "
            "single through-line in the goal; must_include should hold "
            "images, moments, or arguments the writer wants woven in, not "
            "facts to report."
        ),
        "outline_guidance": (
            "Structure by movement of thought, not by topic taxonomy: an "
            "opening scene or question, deepening reflections or arguments, "
            "a turn, and a resonant closing. Chapter titles are evocative "
            "phrases; three to four chapters is usually enough."
        ),
        "section_guidance": (
            "Stay in the writer's single voice throughout. Show through "
            "specific scenes and sensory detail before telling. Do not add "
            "citation markers or bullet lists; let paragraphs flow."
        ),
    },
    "tech_doc": {
        "rubric": [
            {"key": "executability", "name": "Executability",
             "description": "a reader can follow the steps as written and reach the stated result"},
            {"key": "preconditions", "name": "Preconditions & results",
             "description": "each task states what is required before and what success looks like after"},
            {"key": "precision", "name": "Terminology precision",
             "description": "commands, names, and terms are exact and identical across sections"},
            {"key": "coverage", "name": "Task coverage",
             "description": "the reader's core tasks are all documented, including failure handling"},
        ],
        "label_en": "Technical documentation",
        "label_ko": "기술 문서·매뉴얼",
        "research_default": True,
        "citations_enabled": True,
        "intake_priorities": [
            "Reader role, prior knowledge, environment, and relevant versions.",
            "The exact task or successful end state the document must enable.",
            "Prerequisites, constraints, failure cases, and safety boundaries.",
            "Required commands, examples, screenshots, or reference format.",
        ],
        "numbered_headings": True,
        "default_section_length": 500,
        "classify_hint": (
            "technical documentation: how-to guide, manual, API or system "
            "documentation, runbook"
        ),
        "style_hint": "concise instructional register (Korean: -한다/-합니다, imperative steps)",
        "brief_guidance": (
            "Technical documentation serves a reader mid-task. Name the "
            "reader's role and starting knowledge in the audience, and list "
            "the tasks they must be able to complete in the success criteria."
        ),
        "outline_guidance": (
            "Order chapters by the reader's journey: overview and concepts, "
            "prerequisites/setup, core task chapters (one task per section), "
            "then troubleshooting or reference. Every section title should "
            "name a task or a concept, never a vague theme."
        ),
        "section_guidance": (
            "Lead with what the section lets the reader do. Use numbered "
            "steps for procedures, fenced code blocks for commands and "
            "configuration, and note preconditions and expected results. "
            "Keep terminology exactly consistent."
        ),
    },
    "presentation_script": {
        "rubric": [
            {"key": "spokenness", "name": "Spoken naturalness",
             "description": "reads aloud naturally in short spoken sentences; no written-style constructions"},
            {"key": "transitions", "name": "Transitions & signposting",
             "description": "each segment opens from the previous one and the audience always knows where they are"},
            {"key": "engagement", "name": "Audience engagement",
             "description": "direct address, questions, or moments that hold a listening audience"},
            {"key": "pacing", "name": "Message pacing",
             "description": "one idea per segment, a clear single key message, and a closing that repeats it"},
        ],
        "label_en": "Presentation script",
        "label_ko": "발표 대본",
        "research_default": True,
        "citations_enabled": False,
        "intake_priorities": [
            "Audience, event, and why the topic matters in that room.",
            "Target speaking time and whether slides or demonstrations accompany it.",
            "The single key message and action or feeling for the closing.",
            "Speaker persona, formality, and required greeting or acknowledgements.",
        ],
        "numbered_headings": False,
        "default_section_length": 400,
        "classify_hint": (
            "presentation or speech script (발표 대본): spoken text delivered "
            "to a live audience, possibly alongside slides"
        ),
        "style_hint": "spoken register addressed to a live audience (Korean: -합니다/-습니다 구어체)",
        "brief_guidance": (
            "A script is heard once, not re-read. The goal should name what "
            "the audience should remember or do afterwards, the audience "
            "field should describe who is in the room, and must_include "
            "should note the occasion and target speaking length if given."
        ),
        "outline_guidance": (
            "Structure as spoken segments: an opening (greeting, self- "
            "introduction, why this matters to this audience), 2-4 body "
            "segments each carrying one idea, and a closing (recap of the "
            "one key message, call to action, thanks). Each chapter is one "
            "segment of the talk."
        ),
        "section_guidance": (
            "Write exactly what the speaker says, in short spoken sentences. "
            "Open each segment with a transition from the previous one and "
            "use signposting ('먼저', '다음으로', '마지막으로'). Rhetorical "
            "questions and direct address keep attention. You may add brief "
            "stage directions in parentheses, e.g. (잠시 멈춤), (슬라이드 전환), "
            "at most one or two per section. Never use bullet lists, tables, "
            "or citation markers - this text is spoken aloud."
        ),
    },
}


def is_valid_doc_type(key: Any) -> bool:
    return isinstance(key, str) and key in DOC_TYPES


def get_doc_type_profile(key: Any) -> Dict[str, Any]:
    """Profile for a stored document_type; unknown/unset falls back to report."""
    if is_valid_doc_type(key):
        return {"key": key, **DOC_TYPES[key]}
    return {"key": DEFAULT_DOC_TYPE, **DOC_TYPES[DEFAULT_DOC_TYPE]}


def doc_type_choices() -> list[Dict[str, str]]:
    """Ordered choices for the UI and the intake classifier."""
    return [
        {
            "key": key,
            "label_en": profile["label_en"],
            "label_ko": profile["label_ko"],
        }
        for key, profile in DOC_TYPES.items()
    ]
