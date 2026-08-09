"use client";

import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

type Step = "upload" | "requirements" | "outline" | "writer" | "export";
type RequirementView = "all" | "proposal" | "scoring" | "compliance" | "risk" | "conflicts";
type Source = {
  id: string;
  filename: string;
  locator: {
    kind: "page" | "paragraph";
    page?: number | null;
    paragraph_start?: number | null;
    paragraph_end?: number | null;
  };
};
type Requirement = {
  id: string;
  type: "technical_requirement" | "scoring_requirement" | "commercial_requirement" | "qualification_requirement" | "delivery_requirement" | "compliance_requirement" | "format_requirement" | "document_structure_requirement";
  title: string;
  normalized_text: string;
  quote: string;
  importance: "critical" | "high" | "medium" | "low";
  proposal_relevance: boolean;
  proposal_value: number;
  risk_type: "disqualification" | "qualification" | "contract" | "delivery" | null;
  proposal_chapter: string | null;
  response_action: "write_into_proposal" | "write_into_response_table" | "compliance_commitment" | "provide_attachment" | "risk_notice" | "ignore";
  proposal_mapping: string | null;
  scoring_impact: "score_item" | "qualification_pass" | "penalty_risk" | "no_score";
  priority: "P0" | "P1" | "P2" | "P3";
  scoring_relation: "high_score_item" | "medium_score_item" | "requirement_only" | "unknown";
  classification_confidence: number;
  classification_conflict: boolean;
  target_chapter: string | null;
  need_generation: boolean;
  status: "pending" | "confirmed" | "rejected";
  feedback: "pending" | "confirmed" | "not_needed" | "classification_error" | "source_mismatch" | "duplicate" | "incomplete";
  semantic_graph?: {
    entities: Array<{ key: string; type: string; label: string; mention: string; resolved: boolean }>;
    relations: Array<{ subject: string; predicate: string; predicate_label: string; object: string; confidence: number }>;
    actions: Array<{ actor: string; action: string; action_label: string; target: string | null; required: boolean }>;
    focus_summary: string;
    constraints: string[];
    confidence: number;
  };
  sources: Source[];
};
type IgnoreFeedback = Exclude<Requirement["feedback"], "pending" | "confirmed">;
type Conflict = {
  conflict_id: string;
  topic: string;
  conflict_type: "positive_difference" | "compatible_difference" | "potential_conflict" | "true_conflict";
  source_a: { document: string; text: string; role: string };
  source_b: { document: string; text: string; role: string };
  source_a_location: Record<string, number | string | null>;
  source_b_location: Record<string, number | string | null>;
  source_a_authority_level: number;
  source_b_authority_level: number;
  description: string;
  risk_priority: "P0" | "P1" | "P2" | "P3";
  resolution_status: "pending" | "resolved" | "ignored";
  resolution_choice: "choose_a" | "choose_b" | "keep_both" | "request_clarification" | null;
  resolved_by: string | null;
  affected_sections: string[];
};

const ignoreFeedbackLabels: Record<IgnoreFeedback, string> = {
  not_needed: "本次不需要",
  classification_error: "分类错误（含合规误分）",
  source_mismatch: "与原文不符",
  duplicate: "重复内容",
  incomplete: "信息不完整",
};
type SectionVersion = {
  id: string;
  version_no: number;
  content: string;
  origin: "generated" | "edited";
};
type SectionItem = {
  id: string;
  title: string;
  status: string;
  sort_order: number;
  is_recommended: boolean;
  requirement_ids: string[];
  current_version: SectionVersion | null;
  findings: Array<{ id: string; severity: string; message: string }>;
};
type Workspace = {
  id: string;
  name: string;
  status: string;
  document: {
    filename: string;
    source_count: number;
    validation_score?: number | null;
    knowledge_status: string;
  } | null;
  technical_requirements: Requirement[];
  compliance_reminder_count: number;
  response_summary: {
    total: number;
    proposal: number;
    scoring: number;
    compliance: number;
    risk: number;
  };
  outline: SectionItem[];
  estimated_remaining_seconds_low: number | null;
  estimated_remaining_seconds_high: number | null;
  estimate_sample_count: number;
  estimate_basis: string;
  processing_error_code: string | null;
  processing_error_message: string | null;
  processing_retryable: boolean;
  processing_job_status: "queued" | "running" | "succeeded" | "failed" | null;
  processing_job_progress: number;
  processing_job_type: string | null;
  model_calls_used: number;
  model_calls_limit: number;
  model_tokens_used: number;
  model_tokens_limit: number;
  generation_mode: "strict_template" | "planned" | "pdf_template_manual_fill" | "template_conversion_required";
  writer_strategy: "strict_template_writer" | "planned_proposal_writer" | null;
  template_conversion_status: string;
  template_conversion_report: {
    status?: string;
    page_count?: number;
    paragraph_count?: number;
    table_count?: number;
    message?: string;
    template_detected?: boolean;
    structure_validation?: string;
  };
  historical_case_mode: "balanced" | "closest_case" | "structure_only" | "current_only";
  template_filename: string | null;
  template_fidelity: string | null;
  template_fonts: string[];
  template_font_policy: string;
  template_required_fields: string[];
  template_field_values: Record<string, string>;
  template_field_decisions: Array<{
    field_key: string;
    canonical_key: string;
    label: string;
    expected_value_type: string;
    expected_value_type_label: string;
    type_validation: "passed" | "missing";
    value: string | null;
    source_type: string | null;
    source_reference: string | null;
    confidence: number;
    status: "AUTO_FILL" | "REVIEW_REQUIRED" | "MISSING";
    reason: string;
    required: boolean;
    evidence_title: string | null;
    evidence_excerpt: string | null;
    evidence_location: string | null;
    evidence_match_count: number;
    evidence_alternatives: string[];
    slot: {
      document_section?: string | null;
      table_index?: number | null;
      paragraph_index?: number | null;
      row?: number | null;
      column?: number | null;
      surrounding_text?: string;
    };
    semantic_field: string | null;
    expected_entity_type: "Organization" | "Person" | "Project" | null;
    expected_role: "LEGAL_REPRESENTATIVE" | "AUTHORIZED_REPRESENTATIVE" | "PROJECT_MANAGER" | "TECHNICAL_LEAD" | "CONTACT_PERSON" | "SIGNATORY" | null;
    expected_role_label: string | null;
    subject_organization: string | null;
    project_name: string | null;
    binding_status: string | null;
    match_path: string[];
    entity_candidates: Array<{
      person_id: string;
      name: string;
      title: string | null;
      match_basis: string;
      source_document: string | null;
      source_location: string | null;
      confidence: number;
    }>;
    ontology_concept: string;
    display_name: string;
    subject_role: string | null;
    relation_path: string[];
    value_expression: string | null;
    fill_strategy: "direct_attribute" | "composed_value" | "action_only" | "unresolved";
    required_actions: string[];
  }>;
  template_actions: Array<{
    action_id: string;
    display_name: string;
    source_location: string;
    surrounding_text: string;
    relation_path: string[];
    required_actions: string[];
  }>;
  case_library_count: number;
  case_library_name: string;
  case_library_scope: string;
  case_library_fact_usage: string;
  template_outline: Array<{
    title: string;
    level: 1 | 2 | 3 | 4 | 5;
    order: number;
    source: string;
  }>;
};
type ExportItem = { id: string; status: string; filename?: string | null };
type TemplateFieldDecision = Workspace["template_field_decisions"][number];
type ProposalReview = {
  overall: {
    recommended_for_delivery: boolean;
    has_blocking_risk: boolean;
    requirement_coverage_rate: number;
    scoring_coverage_rate: number;
    traceability_rate: number;
    enterprise_fact_verification_rate: number;
    unverified_assertion_count: number;
    internal_identifier_leak_count: number;
    high_risk_count: number;
    blocking_risk_count: number;
  };
  classification_quality: {
    quality_rate: number;
    total_count: number;
    high_confidence_ratio: number;
    low_confidence_count: number;
    unmapped_count: number;
    conflict_count: number;
  };
};
type ResponseSupport = {
  manual_action_archive: {
    total: number;
    pending: number;
    completed: number;
    items: Array<{
      key: string;
      category: "variable" | "format_review" | "material_review" | "content_review" | "conflict_review";
      title: string;
      instruction: string;
      status: "pending" | "completed";
      field_key: string | null;
      value_preview: string | null;
      blocking_scope: string;
    }>;
  };
  response_groups: Array<{
    group_key: string;
    item_count: number;
    titles: string[];
    response_action: Requirement["response_action"];
    target_chapter: string | null;
  }>;
  format_requirements: Array<{
    requirement_id: string;
    title: string;
    instruction: string;
    fidelity: "exact_template" | "structure_preserved";
    manual_check_required: boolean;
    source_text: string;
    sources: Source[];
  }>;
  qualification_responses: Array<{
    requirement_id: string;
    requirement: string;
    status: "matched_verified" | "manual_material_required";
    matches: Array<{
      title: string;
      score: number;
      verified: boolean;
      holder: string | null;
      valid_until: string | null;
      asset_kind: "image" | "document";
      asset_available: boolean;
      source_file: string;
      source_location: string | null;
      source_page: number | null;
      source_excerpt: string | null;
      target_location: string;
      insertion_status: "ready_for_review" | "source_location_required" | "asset_required";
      rationale: string;
    }>;
  }>;
  traceability: {
    requirements: Array<{
      requirement_id: string;
      title: string;
      source_text: string;
      sources: Source[];
      response_action: Requirement["response_action"];
      generated_sections: string[];
    }>;
    generated_paragraphs: Array<{
      section_id: string;
      section_title: string;
      paragraph_index: number;
      generated_text: string;
      origin: "generated" | "edited" | "auto_fixed";
      sources: Array<{
        source_type: string;
        source_title: string;
        source_location: string | null;
        source_excerpt: string | null;
        usage_description: string;
        verification_status: string;
      }>;
    }>;
  };
};
type AccessStatus = {
  required: boolean;
  authorized: boolean;
};

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1").replace(/\/$/, "");
const READY_WORKSPACE_STATUSES = new Set([
  "outline_ready",
  "writing",
  "ready_to_export",
  "exported",
]);
const workspaceStatusLabels: Record<string, string> = {
  validating: "正在检查招标文件有效性",
  extracting: "正在提取技术要求与评分点",
  planning: "正在生成推荐目录",
};
const steps: Array<{ id: Step; title: string; subtitle: string }> = [
  { id: "upload", title: "上传文件", subtitle: "自动识别与解析" },
  { id: "requirements", title: "招标响应分析", subtitle: "响应事项与评分点" },
  { id: "outline", title: "推荐目录", subtitle: "确认章节结构" },
  { id: "writer", title: "章节写作", subtitle: "生成、编辑、校核" },
  { id: "export", title: "导出 Word", subtitle: "交付技术方案" },
];
const templateSteps: Array<{ id: Step; title: string; subtitle: string }> = [
  { id: "upload", title: "上传文件", subtitle: "自动识别格式" },
  { id: "export", title: "回填与审核", subtitle: "查看依据并导出" },
];
const typeLabels: Record<Requirement["type"], string> = {
  technical_requirement: "技术要求",
  scoring_requirement: "评分要求",
  commercial_requirement: "商务要求",
  qualification_requirement: "资格要求",
  delivery_requirement: "交付要求",
  compliance_requirement: "合规要求",
  format_requirement: "格式要求",
  document_structure_requirement: "文档结构要求",
};
const responseActionLabels: Record<Requirement["response_action"], string> = {
  write_into_proposal: "写入技术方案",
  write_into_response_table: "加入响应表",
  compliance_commitment: "商务/合规承诺",
  provide_attachment: "提供附件材料",
  risk_notice: "风险提醒",
  ignore: "忽略",
};
const scoringImpactLabels: Record<Requirement["scoring_impact"], string> = {
  score_item: "影响评分",
  qualification_pass: "资格通过项",
  penalty_risk: "不响应存在风险",
  no_score: "不直接计分",
};
const requirementTabs: Array<{ id: RequirementView; label: string }> = [
  { id: "all", label: "全部" },
  { id: "proposal", label: "技术方案" },
  { id: "scoring", label: "评分响应" },
  { id: "compliance", label: "商务合规" },
  { id: "risk", label: "风险提醒" },
  { id: "conflicts", label: "冲突事项" },
];
const importanceLabels: Record<Requirement["importance"], string> = {
  critical: "关键",
  high: "重要",
  medium: "一般",
  low: "低",
};
const importanceRank: Record<Requirement["importance"], number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};
function entityLabel(item: Requirement, key: string | null) {
  return item.semantic_graph?.entities.find((entity) => entity.key === key)?.label ?? "相关主体";
}
const fillStatusLabels = {
  AUTO_FILL: "可自动填写",
  REVIEW_REQUIRED: "待人工确认",
  MISSING: "资料缺失",
};
const priorityRank: Record<Requirement["priority"], number> = {
  P0: 0,
  P1: 1,
  P2: 2,
  P3: 3,
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.error?.message ?? `操作失败（${response.status}）`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function sourceLabel(source: Source) {
  if (source.locator.kind === "page") return `第 ${source.locator.page} 页`;
  const start = source.locator.paragraph_start;
  const end = source.locator.paragraph_end;
  return `第 ${start === end ? start : `${start}-${end}`} 段`;
}

function isInternalEvidenceLabel(value: string | null | undefined) {
  return Boolean(value && /^(?:current_project|manual_verified|historical_case|tender_document|custom_)/i.test(value));
}

function visibleEvidenceSource(item: TemplateFieldDecision) {
  if (item.evidence_title && !isInternalEvidenceLabel(item.evidence_title)) return item.evidence_title;
  if (item.source_type === "tender_document") return "当前采购文件";
  if (item.source_type === "manual_verified") return "人工已确认的机构私有资料";
  if (item.source_type === "historical_case") return "大岳五案例私有库";
  return "机构私有资料库";
}

function visibleEvidenceLocation(item: TemplateFieldDecision) {
  if (item.evidence_location && !isInternalEvidenceLabel(item.evidence_location)) return item.evidence_location;
  return item.source_type === "tender_document"
    ? "当前采购文件（来源记录暂未提供页码或段落）"
    : "机构私有资料（来源记录暂未提供章节、页码或附件位置）";
}

function highlightedEvidence(text: string, value: string | null) {
  if (!value) return text;
  const index = text.toLocaleLowerCase().indexOf(value.toLocaleLowerCase());
  if (index < 0) return text;
  return <>{text.slice(0, index)}<mark>{text.slice(index, index + value.length)}</mark>{text.slice(index + value.length)}</>;
}

function WordDocumentPreview({ workspace }: { workspace: Workspace }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [previewState, setPreviewState] = useState<"loading" | "ready" | "error">("loading");
  const revision = (workspace.template_field_decisions ?? [])
    .map((item) => `${item.field_key}:${item.status}:${item.value ?? ""}`)
    .join("|");

  useEffect(() => {
    let cancelled = false;
    let resizeObserver: ResizeObserver | null = null;
    setPreviewState("loading");
    void (async () => {
      try {
        const response = await fetch(`${API_BASE}/workspaces/${workspace.id}/template-preview`, {
          credentials: "same-origin",
          cache: "no-store",
        });
        if (!response.ok) throw new Error("preview unavailable");
        const data = await response.arrayBuffer();
        const { renderAsync } = await import("docx-preview");
        if (cancelled || !containerRef.current) return;
        containerRef.current.replaceChildren();
        await renderAsync(data, containerRef.current, undefined, {
          className: "word-page",
          inWrapper: true,
          breakPages: true,
          ignoreWidth: false,
          ignoreHeight: false,
          ignoreFonts: false,
        });
        const updateScale = () => {
          if (!containerRef.current) return;
          const page = containerRef.current.querySelector<HTMLElement>("section.docx");
          if (!page) return;
          const availableWidth = Math.max(280, containerRef.current.clientWidth - 24);
          const naturalWidth = page.offsetWidth || 794;
          containerRef.current.style.setProperty(
            "--word-preview-scale",
            String(Math.min(1, availableWidth / naturalWidth)),
          );
        };
        updateScale();
        resizeObserver = new ResizeObserver(updateScale);
        resizeObserver.observe(containerRef.current);
        if (!cancelled) setPreviewState("ready");
      } catch {
        if (!cancelled) setPreviewState("error");
      }
    })();
    return () => {
      cancelled = true;
      resizeObserver?.disconnect();
    };
  }, [workspace.id, revision]);

  return <div className="word-preview-shell">
    {previewState === "loading" && <div className="word-preview-status">正在生成 Word 页面预览…</div>}
    {previewState === "error" && <div className="word-preview-status error">Word 预览暂时未生成，请刷新重试；原格式导出不受影响。</div>}
    <div ref={containerRef} className="word-preview-canvas" aria-label="实际回填 Word 文档预览" />
  </div>;
}

function estimateLabel(item: Workspace) {
  const low = item.estimated_remaining_seconds_low;
  const high = item.estimated_remaining_seconds_high;
  if (low == null || high == null) {
    return "暂无可靠预计时长，系统正在记录本次真实耗时";
  }
  if (high <= 0) return "即将完成";
  const lowMinutes = Math.max(1, Math.ceil(low / 60));
  const highMinutes = Math.max(lowMinutes, Math.ceil(high / 60));
  const range = lowMinutes === highMinutes
    ? `约 ${highMinutes} 分钟`
    : `约 ${lowMinutes}–${highMinutes} 分钟`;
  return `预计还需 ${range}（基于 ${item.estimate_sample_count} 次本机历史工作量）`;
}

export default function Home() {
  const [accessState, setAccessState] = useState<"checking" | "required" | "authorized">("checking");
  const [inviteCode, setInviteCode] = useState("");
  const [inviteError, setInviteError] = useState("");
  const [authorizing, setAuthorizing] = useState(false);
  const [step, setStep] = useState<Step>("upload");
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [requirementView, setRequirementView] = useState<RequirementView>("all");
  const [ignoreMenuId, setIgnoreMenuId] = useState("");
  const [sections, setSections] = useState<SectionItem[]>([]);
  const [activeSectionId, setActiveSectionId] = useState("");
  const [editorContent, setEditorContent] = useState("");
  const [generationInstruction, setGenerationInstruction] = useState("");
  const [minChapterChars, setMinChapterChars] = useState(800);
  const [maxChapterChars, setMaxChapterChars] = useState(5000);
  const [exportItem, setExportItem] = useState<ExportItem | null>(null);
  const [proposalReview, setProposalReview] = useState<ProposalReview | null>(null);
  const [responseSupport, setResponseSupport] = useState<ResponseSupport | null>(null);
  const [caseReferenceMode, setCaseReferenceMode] = useState<"balanced" | "closest_case" | "structure_only" | "current_only">("balanced");
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [evidenceItem, setEvidenceItem] = useState<TemplateFieldDecision | null>(null);
  const [editingFieldKey, setEditingFieldKey] = useState("");
  const [editingFieldValue, setEditingFieldValue] = useState("");

  const activeSection = sections.find((item) => item.id === activeSectionId);
  const feedbackSummary = useMemo(() => ({
    confirmed: requirements.filter((item) => item.feedback === "confirmed").length,
    ignored: requirements.filter((item) => item.feedback !== "pending" && item.feedback !== "confirmed").length,
    issues: requirements.filter((item) => ["classification_error", "source_mismatch", "duplicate", "incomplete"].includes(item.feedback)).length,
    pending: requirements.filter((item) => item.feedback === "pending").length,
  }), [requirements]);
  const grouped = useMemo(() => {
    const sorted = [...requirements].sort((left, right) => {
      const otherDelta = Number(left.type === "compliance_requirement") - Number(right.type === "compliance_requirement");
      if (otherDelta) return otherDelta;
      const priorityDelta = priorityRank[left.priority] - priorityRank[right.priority];
      if (priorityDelta) return priorityDelta;
      const importanceDelta = importanceRank[left.importance] - importanceRank[right.importance];
      if (importanceDelta) return importanceDelta;
      return right.proposal_value - left.proposal_value;
    });
    const groups = sorted.reduce<Record<string, Requirement[]>>((result, item) => {
      const chapter = requirementView !== "proposal"
        ? typeLabels[item.type]
        : item.proposal_mapping ?? "其他技术要求";
      result[chapter] = [...(result[chapter] ?? []), item];
      return result;
    }, {});
    return Object.fromEntries(
      Object.entries(groups).sort(([leftChapter, leftItems], [rightChapter, rightItems]) => {
        const otherDelta = Number(leftChapter.includes("其他")) - Number(rightChapter.includes("其他"));
        if (otherDelta) return otherDelta;
        return Math.min(...leftItems.map((item) => importanceRank[item.importance]))
          - Math.min(...rightItems.map((item) => importanceRank[item.importance]));
      }),
    );
  }, [requirements, requirementView]);
  const usesTemplateFlow = workspace?.generation_mode !== "planned";
  const conversionPending = workspace?.generation_mode === "template_conversion_required"
    || workspace?.generation_mode === "pdf_template_manual_fill";
  const visibleSteps = !workspace
    ? [templateSteps[0]]
    : usesTemplateFlow ? templateSteps : steps;
  const progress = workspace
    ? Math.max(20, ((visibleSteps.findIndex((item) => item.id === step) + 1) / visibleSteps.length) * 100)
    : 0;
  const missingTemplateDecisions = (workspace?.template_field_decisions ?? []).filter(
    (item) => item.required && item.status === "MISSING",
  );

  useEffect(() => {
    let active = true;
    void request<AccessStatus>("/access/status")
      .then((result) => {
        if (!active) return;
        setAccessState(result.authorized ? "authorized" : "required");
      })
      .catch(() => {
        if (active) {
          setAccessState("required");
          setInviteError("暂时无法验证访问权限，请稍后重试。");
        }
      });
    return () => {
      active = false;
    };
  }, []);

  async function authorizeInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthorizing(true);
    setInviteError("");
    try {
      await request<{ authorized: boolean }>("/access/invite", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: inviteCode }),
      });
      setInviteCode("");
      setAccessState("authorized");
    } catch (caught) {
      setInviteError(
        caught instanceof Error ? caught.message : "邀请码验证失败。",
      );
    } finally {
      setAuthorizing(false);
    }
  }

  async function openCompletedWorkspace(completed: Workspace, message?: string) {
    const [allRequirements, support] = await Promise.all([
      request<Requirement[]>(`/workspaces/${completed.id}/requirements?view=proposal`),
      request<ResponseSupport>(`/workspaces/${completed.id}/response-support`),
    ]);
    setWorkspace(completed);
    setRequirements(allRequirements);
    setResponseSupport(support);
    setRequirementView("proposal");
    setSections(completed.outline);
    setActiveSectionId(completed.outline[0]?.id ?? "");
    setEditorContent(completed.outline[0]?.current_version?.content ?? "");
    setStep(completed.generation_mode === "planned" ? "requirements" : "export");
    setNotice(
      message
      ?? `处理完成，已分析 ${completed.response_summary.total} 条响应事项。`,
    );
  }

  async function waitForWorkspace(workspaceId: string, initial: Workspace) {
    let completed = initial;
    let consecutiveNetworkErrors = 0;
    let lastPollingError = "";
    while (!READY_WORKSPACE_STATUSES.has(completed.status)) {
      if (completed.status === "draft") {
        throw new Error(
          completed.processing_error_message
          ?? "文件已上传并解析，但后台处理未完成，可点击“继续处理”重试。",
        );
      }
      const stageLabel = workspaceStatusLabels[completed.status] ?? "正在处理招标文件";
      setBusy(`${stageLabel} · ${estimateLabel(completed)}，完成后自动打开`);
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
      try {
        completed = await request<Workspace>(`/workspaces/${workspaceId}`);
        consecutiveNetworkErrors = 0;
        setWorkspace(completed);
      } catch (caught) {
        consecutiveNetworkErrors += 1;
        lastPollingError = caught instanceof Error
          ? caught.message
          : "无法读取处理进度";
        if (consecutiveNetworkErrors >= 5) {
          throw new Error(
            `处理进度读取失败：${lastPollingError}。后台任务可能仍在运行，请保持当前页面并稍后重试。`,
          );
        }
      }
    }
    return completed;
  }

  const run = useCallback(async (label: string, action: () => Promise<void>) => {
    setBusy(label);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "操作失败，请稍后重试。");
    } finally {
      setBusy("");
    }
  }, []);

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    await run("正在识别、解析并规划技术方案", async () => {
      const form = new FormData();
      form.append("file", file);
      const created = await request<Workspace>("/workspaces", { method: "POST", body: form });
      setWorkspace(created);
      let completed = await waitForWorkspace(created.id, created);
      if (
        completed.generation_mode === "strict_template"
        && completed.outline.length > 0
      ) {
        completed = await request<Workspace>(
          `/workspaces/${completed.id}/generate-draft`,
          { method: "POST" },
        );
        while (
          completed.processing_job_type === "autonomous_draft"
          && ["queued", "running"].includes(completed.processing_job_status ?? "")
        ) {
          setBusy(`正在按原格式自动生成 · ${completed.processing_job_progress}%`);
          await new Promise((resolve) => window.setTimeout(resolve, 2000));
          completed = await request<Workspace>(`/workspaces/${completed.id}`);
        }
        if (completed.processing_job_status === "failed") {
          throw new Error(completed.processing_error_message ?? "自动生成失败，已保留成功结果。");
        }
      }
      await openCompletedWorkspace(
        completed,
        completed.generation_mode === "strict_template"
          ? "已识别可编辑响应格式并完成自动预填，请审核候选值及来源。"
          : completed.generation_mode === "planned"
            ? `已确认文件无响应模板，分析 ${completed.response_summary.total} 条响应事项。`
            : "检测到 PDF，但尚无法可靠转换为可编辑 Word。系统未进入目录生成。",
      );
    });
  }

  async function retryWorkspace() {
    if (!workspace) return;
    await run("正在从中断位置继续处理", async () => {
      const resumed = await request<Workspace>(
        `/workspaces/${workspace.id}/retry`,
        { method: "POST" },
      );
      setWorkspace(resumed);
      const completed = await waitForWorkspace(workspace.id, resumed);
      await openCompletedWorkspace(completed, "已从中断位置继续并完成目录规划。");
    });
  }

  async function showRequirements(view: RequirementView) {
    if (!workspace) return;
    await run("正在读取响应事项", async () => {
      if (view === "conflicts") {
        const items = await request<Conflict[]>(`/workspaces/${workspace.id}/conflicts`);
        setConflicts(items);
        setRequirementView(view);
        setNotice(items.length === 0 ? "未发现需要关注的文件差异。" : "");
        return;
      }
      const items = await request<Requirement[]>(`/workspaces/${workspace.id}/requirements?view=${view}`);
      setRequirements(items);
      setRequirementView(view);
      setNotice(items.length === 0 ? "当前分类下没有响应事项。" : "");
    });
  }

  async function resolveConflict(
    item: Conflict,
    choice: "choose_a" | "choose_b" | "keep_both" | "request_clarification",
  ) {
    if (!workspace) return;
    await run("正在保存冲突处理口径", async () => {
      await request<Conflict>(
        `/workspaces/${workspace.id}/conflicts/${item.conflict_id}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            choice,
            resolved_by: "当前最终确认人",
          }),
        },
      );
      const items = await request<Conflict[]>(`/workspaces/${workspace.id}/conflicts`);
      setConflicts(items);
      setNotice(
        choice === "request_clarification"
          ? "已提交澄清；只暂停受影响章节。"
          : "最终响应口径已保存。",
      );
    });
  }

  async function recordRequirementFeedback(
    item: Requirement,
    feedback: Requirement["feedback"],
  ) {
    if (!workspace) return;
    await run("正在保存人工确认", async () => {
      const updated = await request<Requirement>(
        `/workspaces/${workspace.id}/requirements/${item.id}/feedback`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ feedback }),
        },
      );
      const refreshed = await request<Workspace>(
        `/workspaces/${workspace.id}`,
      );
      setRequirements((items) => items.map((current) => current.id === updated.id ? updated : current));
      setWorkspace({
        ...refreshed,
        technical_requirements: refreshed.technical_requirements.map(
          (requirement) => requirement.id === updated.id
            ? updated
            : requirement,
        ),
      });
      setSections(refreshed.outline);
      setActiveSectionId((current) => (
        refreshed.outline.some((section) => section.id === current)
          ? current
          : refreshed.outline[0]?.id ?? ""
      ));
      setIgnoreMenuId("");
      setNotice(
        feedback === "source_mismatch"
          ? "已记录为与原文不符；相同错误内容下次将被自动过滤。"
          : feedback === "classification_error"
          ? "已记录分类错误，后续分类复核将使用这条反馈。"
          : feedback === "duplicate"
          ? "已记录为重复内容。"
          : feedback === "incomplete"
          ? "已记录为信息不完整，后续需要重新核对原文。"
          : "人工确认结果已保存。",
      );
    });
  }

  async function updateRequirementStrategy(
    item: Requirement,
    target: "proposal" | "compliance",
  ) {
    if (!workspace) return;
    await run("正在调整响应策略", async () => {
      await request<Requirement>(
        `/workspaces/${workspace.id}/requirements/${item.id}/strategy`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target }),
        },
      );
      const [refreshed, visibleItems] = await Promise.all([
        request<Workspace>(`/workspaces/${workspace.id}`),
        request<Requirement[]>(
          `/workspaces/${workspace.id}/requirements?view=${requirementView}`,
        ),
      ]);
      setWorkspace(refreshed);
      setRequirements(visibleItems);
      setSections(refreshed.outline);
      setActiveSectionId((current) => (
        refreshed.outline.some((section) => section.id === current)
          ? current
          : refreshed.outline[0]?.id ?? ""
      ));
      setNotice(
        target === "proposal"
          ? "已转入技术方案，并同步到推荐目录。"
          : "已转入商务合规，不再进入技术方案正文。",
      );
    });
  }

  function updateChapter(index: number, title: string) {
    setSections((items) => items.map((item, current) => current === index ? { ...item, title } : item));
  }

  function moveChapter(index: number, direction: -1 | 1) {
    setSections((items) => {
      const target = index + direction;
      if (target < 0 || target >= items.length) return items;
      const copy = [...items];
      [copy[index], copy[target]] = [copy[target], copy[index]];
      return copy.map((item, position) => ({ ...item, sort_order: position + 1 }));
    });
  }

  async function saveOutline() {
    if (!workspace) return;
    await run("正在保存目录", async () => {
      const eligibleRequirementIds = new Set(
        workspace.technical_requirements
          .filter((item) => item.status !== "rejected")
          .map((item) => item.id),
      );
      const chapters = sections
        .map((item) => ({
          title: item.title,
          requirement_ids: item.requirement_ids.filter(
            (requirementId) => eligibleRequirementIds.has(requirementId),
          ),
        }))
        .filter((item) => item.requirement_ids.length > 0);
      if (chapters.length === 0) {
        throw new Error("当前没有需要写入技术方案的内容，请返回调整处理方式。");
      }
      const saved = await request<SectionItem[]>(`/workspaces/${workspace.id}/outline`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chapters }),
      });
      setSections(saved);
      setActiveSectionId(saved[0]?.id ?? "");
      setStep("writer");
      setNotice("目录已确认，可以按章节生成。");
    });
  }

  function selectSection(section: SectionItem) {
    setActiveSectionId(section.id);
    setEditorContent(section.current_version?.content ?? "");
    setGenerationInstruction("");
  }

  async function generateSection(section: SectionItem) {
    if (!workspace) return;
    await run(`正在生成《${section.title}》`, async () => {
      let current = await request<Workspace>(
        `/workspaces/${workspace.id}/sections/${section.id}/generate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            instruction: generationInstruction.trim() || null,
            case_reference_mode: caseReferenceMode,
            min_chars: minChapterChars,
            max_chars: maxChapterChars,
          }),
        },
      );
      while (
        current.processing_job_type === "section_generation"
        && ["queued", "running"].includes(current.processing_job_status ?? "")
      ) {
        setBusy(`正在后台生成《${section.title}》 · ${current.processing_job_progress}%`);
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        current = await request<Workspace>(`/workspaces/${workspace.id}`);
      }
      if (current.processing_job_status === "failed") {
        throw new Error(
          current.processing_error_message
          ?? "章节生成失败，已保留现有内容，可继续重试。",
        );
      }
      const generated = current.outline.find((item) => item.id === section.id);
      if (!generated?.current_version) throw new Error("章节生成未完成，请稍后重试。");
      setWorkspace(current);
      setSections(current.outline);
      setActiveSectionId(generated.id);
      setEditorContent(generated.current_version?.content ?? "");
      setGenerationInstruction("");
      setNotice("章节已生成，请人工检查并补充企业真实信息。");
    });
  }

  async function generateCompleteDraft() {
    if (!workspace) return;
    await run("正在后台生成整本初稿", async () => {
      let current = await request<Workspace>(
        `/workspaces/${workspace.id}/generate-draft`,
        { method: "POST" },
      );
      while (
        current.processing_job_type === "autonomous_draft"
        && ["queued", "running"].includes(current.processing_job_status ?? "")
      ) {
        setBusy(`正在后台生成整本初稿 · ${current.processing_job_progress}%`);
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        current = await request<Workspace>(`/workspaces/${workspace.id}`);
      }
      if (current.processing_job_status === "failed") {
        throw new Error(
          current.processing_error_message
          ?? "整本初稿生成失败，已保留成功章节，可继续重试。",
        );
      }
      setWorkspace(current);
      setSections(current.outline);
      const selected = current.outline.find((item) => !item.current_version)
        ?? current.outline[0];
      setActiveSectionId(selected?.id ?? "");
      setEditorContent(selected?.current_version?.content ?? "");
      setNotice("整本初稿已生成并完成自动校核，请逐章人工确认后导出。");
    });
  }

  async function saveSection() {
    if (!workspace || !activeSection?.current_version) return;
    await run("正在保存人工修改", async () => {
      const saved = await request<SectionItem>(
        `/workspaces/${workspace.id}/sections/${activeSection.id}/content`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            base_version_id: activeSection.current_version?.id,
            content: editorContent,
          }),
        },
      );
      setSections((items) => items.map((item) => item.id === saved.id ? saved : item));
      setEditorContent(saved.current_version?.content ?? "");
      setNotice("人工修改已保存，并已重新执行合规校核。");
    });
  }

  async function approveSection() {
    if (!workspace || !activeSection) return;
    await run("正在确认章节", async () => {
      const approved = await request<SectionItem>(
        `/workspaces/${workspace.id}/sections/${activeSection.id}/approve`,
        { method: "POST" },
      );
      setSections((items) => items.map((item) => item.id === approved.id ? approved : item));
      setNotice("章节已确认，可导出 Word。");
    });
  }

  async function createExport() {
    if (!workspace) return;
    await run("正在校核并生成 Word", async () => {
      const created = await request<ExportItem>(`/workspaces/${workspace.id}/exports`, {
        method: "POST",
      });
      const review = await request<ProposalReview>(
        `/workspaces/${workspace.id}/review`,
      );
      const support = await request<ResponseSupport>(
        `/workspaces/${workspace.id}/response-support`,
      );
      setExportItem(created);
      setProposalReview(review);
      setResponseSupport(support);
      setNotice(
        workspace.generation_mode === "strict_template" && missingTemplateDecisions.length > 0
          ? `Word 已生成；${missingTemplateDecisions.length} 项资料需在企业数据库补齐，系统未猜写。`
          : review.overall.recommended_for_delivery
          ? "校核完成，Word 文件已经生成。"
          : `Word 已生成，有 ${review.overall.blocking_risk_count} 项建议人工留意。`,
      );
    });
  }

  async function approveTemplateAndExport() {
    if (!workspace) return;
    await run("正在确认预填结果并生成 Word", async () => {
      let currentSections = [...sections];
      for (const section of currentSections) {
        if (section.current_version && section.status !== "approved") {
          const approved = await request<SectionItem>(
            `/workspaces/${workspace.id}/sections/${section.id}/approve`,
            { method: "POST" },
          );
          currentSections = currentSections.map((item) => item.id === approved.id ? approved : item);
        }
      }
      setSections(currentSections);
      const created = await request<ExportItem>(
        `/workspaces/${workspace.id}/exports`,
        { method: "POST" },
      );
      setExportItem(created);
      setNotice("审核结果已记录，原格式 Word 已生成。");
    });
  }

  async function reviewTemplateField(fieldKey: string, action: "confirm" | "reset", value?: string) {
    if (!workspace) return;
    await run(action === "confirm" ? "正在确认字段" : "正在恢复审核", async () => {
      const updated = await request<Workspace>(
        `/workspaces/${workspace.id}/template-fields/review`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ field_key: fieldKey, action, value }),
        },
      );
      setWorkspace(updated);
      setEditingFieldKey("");
      setEditingFieldValue("");
      setNotice(action === "confirm" ? "字段已确认并记录来源。" : "字段已恢复为待审核状态。");
    });
  }

  async function bindEntityRole(
    item: TemplateFieldDecision,
    candidate: TemplateFieldDecision["entity_candidates"][number],
  ) {
    if (!workspace || !item.expected_role) return;
    await run(`正在绑定${item.expected_role_label ?? "项目角色"}`, async () => {
      const updated = await request<Workspace>(
        `/workspaces/${workspace.id}/role-bindings`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            role: item.expected_role,
            person_id: candidate.person_id,
          }),
        },
      );
      setWorkspace(updated);
      setNotice(`已将${candidate.name}绑定为${item.expected_role_label ?? "当前角色"}。`);
    });
  }

  function startEditingTemplateField(item: TemplateFieldDecision) {
    setEditingFieldKey(item.field_key);
    setEditingFieldValue(item.value ?? "");
  }

  if (accessState !== "authorized") {
    return (
      <main className="invite-shell">
        <section className="invite-card">
          <div className="brand-seal invite-seal">岳</div>
          <span className="panel-label">PRIVATE PREVIEW</span>
          <h1>技术方案工作台</h1>
          {accessState === "checking" ? (
            <p>正在验证访问权限…</p>
          ) : (
            <>
              <p>本工作台仅向受邀用户开放。请输入邀请人提供的邀请码。</p>
              <form onSubmit={authorizeInvite}>
                <label htmlFor="invite-code">邀请码</label>
                <input
                  id="invite-code"
                  value={inviteCode}
                  minLength={4}
                  maxLength={128}
                  autoComplete="one-time-code"
                  onChange={(event) => setInviteCode(event.target.value)}
                  placeholder="请输入邀请码"
                  required
                />
                {inviteError && <div className="invite-error">{inviteError}</div>}
                <button
                  className="primary large"
                  type="submit"
                  disabled={authorizing}
                >
                  {authorizing ? "正在验证…" : "进入工作台"}
                </button>
              </form>
              <small>邀请码不会保存在浏览器页面中，请勿转发给无关人员。</small>
            </>
          )}
        </section>
      </main>
    );
  }

  return (
    <main className="workbench">
      <header className="masthead">
        <div className="brand-lockup">
          <div className="brand-seal">岳</div>
          <div><small>DAYUE BID AGENT</small><h1>技术方案工作台</h1></div>
        </div>
        <div className="project-switcher">
          <span>{workspace ? workspace.name : "上传招标文件即可开始"}</span>
          <b className="live-badge">机构私有</b>
        </div>
      </header>

      <div className="workspace">
        <aside className="rail">
          <div className="progress-box">
            <span>方案进度</span><strong>{progress}%</strong>
            <i><em style={{ width: `${progress}%` }} /></i>
          </div>
          <nav>
            {visibleSteps.map((item, index) => (
              <button
                key={item.id}
                className={step === item.id ? "active" : ""}
                disabled={!workspace && item.id !== "upload"}
                onClick={() => setStep(item.id)}
              >
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div><strong>{item.title}</strong><small>{item.subtitle}</small></div>
              </button>
            ))}
          </nav>
          <div className="privacy-note">
            <strong>私有知识库边界</strong>
            <p>页面刷新或重新打开后会回到上传入口，不显示历史方案或历史导出文件。其他 IP 无法读取或下载。</p>
          </div>
        </aside>

        <section className="stage">
          <div className="stage-header">
            <div>
              <span className="eyebrow">CONTROLLED PROPOSAL WORKFLOW</span>
              <h2>{visibleSteps.find((item) => item.id === step)?.title}</h2>
              <p>{!workspace ? "PDF 先转为可编辑 Word，再自动判断是否存在响应模板。" : workspace.generation_mode === "strict_template" ? "已检测到可编辑响应模板：系统自动预填，业务人员只审核。" : workspace.generation_mode === "planned" ? "已确认无响应模板：进入目录与方案生成。" : "PDF 转 Word 尚未通过结构验证：未进入任何写作引擎。"}</p>
            </div>
            {busy && <div className="busy-pill" role="status" aria-live="polite"><i />{busy}</div>}
          </div>
          {error && (
            <div className="message error">
              <span>{error}</span>
              {workspace?.status === "draft" && workspace.processing_retryable && (
                <button onClick={retryWorkspace}>继续处理</button>
              )}
            </div>
          )}
          {notice && <div className="message success">{notice}</div>}

          {step === "upload" && (
            <div className="upload-hero">
              <span className="panel-label">START FROM THE TENDER</span>
              <h3>只需上传招标文件</h3>
              <p>DOCX 直接检测；PDF 先在私有环境转成可编辑 Word 再检测。有模板严格回填，确认无模板才生成目录。</p>
              <label className={`upload-zone hero ${busy ? "disabled" : ""}`}>
                <input type="file" accept=".pdf,.docx" disabled={Boolean(busy)} onChange={upload} />
                <strong>选择 PDF 或 DOCX 招标文件</strong>
                <span>文件仅在机构私有环境中处理</span>
              </label>
              <div className="pipeline">
                {["文件检查", "格式识别", "数据匹配", "自动预填", "人工审核"].map((item, index) => (
                  <div key={item}><b>{index + 1}</b><span>{item}</span></div>
                ))}
              </div>
            </div>
          )}

          {step === "requirements" && (
            <div className="requirement-layout">
              <div className="section-toolbar response-summary">
                <div><strong>{workspace?.response_summary?.total ?? 0}</strong><span>总响应事项</span></div>
                <div><strong>{workspace?.response_summary?.proposal ?? 0}</strong><span>技术方案事项</span></div>
                <div><strong>{workspace?.response_summary?.scoring ?? 0}</strong><span>评分响应事项</span></div>
                <div><strong>{workspace?.response_summary?.compliance ?? 0}</strong><span>商务合规事项</span></div>
                <div><strong>{workspace?.response_summary?.risk ?? 0}</strong><span>P0 风险事项</span></div>
                <button className="primary" disabled={Boolean(busy)} onClick={() => setStep("outline")}>下一步：查看推荐目录</button>
              </div>
              <div className="requirement-tabs" role="tablist" aria-label="要求分类">
                {requirementTabs.map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    role="tab"
                    aria-selected={requirementView === tab.id}
                    className={requirementView === tab.id ? "active" : ""}
                    disabled={Boolean(busy)}
                    onClick={() => showRequirements(tab.id)}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
              <div className="requirement-guidance">
                <div>
                  <strong>响应事项分析</strong>
                  <span>这里回答“如何响应、写在哪里、有什么风险”；人工切换归类会同步更新推荐目录。</span>
                </div>
                <div className="feedback-summary" aria-label="人工确认进度">
                  <span><b>{feedbackSummary.pending}</b> 待判断</span>
                  <span><b>{feedbackSummary.ignored}</b> 已忽略</span>
                  {feedbackSummary.issues > 0 && <span className="warning"><b>{feedbackSummary.issues}</b> 条问题反馈</span>}
                </div>
              </div>
              {responseSupport && (responseSupport.format_requirements.length > 0 || responseSupport.qualification_responses.length > 0) && (
                <div className="support-overview">
                  <details open={responseSupport.format_requirements.some((item) => item.fidelity === "exact_template")}>
                    <summary>交付格式清单 <b>{responseSupport.format_requirements.length}</b></summary>
                    {responseSupport.format_requirements.length === 0 ? <p>未识别到独立格式约束。</p> : responseSupport.format_requirements.map((item) => (
                      <article key={item.requirement_id}>
                        <strong>{item.title}</strong>
                        <span>{item.fidelity === "exact_template" ? "必须按原模板填写，导出后人工复核" : "保持字段和结构一致"}</span>
                        <p>{item.instruction}</p>
                        <details><summary>查看招标原文</summary><blockquote>{item.source_text}</blockquote></details>
                      </article>
                    ))}
                  </details>
                  <details>
                    <summary>资格材料响应 <b>{responseSupport.qualification_responses.length}</b></summary>
                    {responseSupport.qualification_responses.length === 0 ? <p>当前未识别到资格附件事项。</p> : responseSupport.qualification_responses.map((item) => (
                      <article key={item.requirement_id}>
                        <strong>{item.requirement}</strong>
                        <span>{item.status === "matched_verified" ? "已匹配核验材料" : "未找到已核验材料，需人工补充"}</span>
                        {item.matches.map((match, matchIndex) => (
                          <details key={`${match.title}-${matchIndex}`}>
                            <summary>{match.title} · 匹配 {Math.round(match.score * 100)}% · {match.verified ? "事实已核验" : "待核验"}</summary>
                            <p>材料：{match.asset_kind === "image" ? "图片/扫描件" : "文档附件"} · {match.asset_available ? "文件已关联" : "尚未关联真实文件"}</p>
                            <p>来源：{match.source_file}{match.source_page ? ` · 第 ${match.source_page} 页` : ""}{match.source_location ? ` · ${match.source_location}` : " · 尚缺原文件位置"}</p>
                            <p>回填位置：{match.target_location} · {match.insertion_status === "ready_for_review" ? "可进入人工审核" : "补齐文件及定位后再回填"}</p>
                            {match.source_excerpt && <blockquote>{match.source_excerpt}</blockquote>}
                          </details>
                        ))}
                      </article>
                    ))}
                  </details>
                </div>
              )}
              {requirementView === "conflicts" && conflicts.map((item) => (
                <article className={`requirement-card ${item.risk_priority === "P0" ? "scoring-card" : ""}`} key={item.conflict_id}>
                  <div className="requirement-top">
                    <div className="requirement-tags">
                      <span className="type-tag compliance_requirement">
                        {item.conflict_type === "true_conflict" ? "真实冲突" : item.conflict_type === "positive_difference" ? "评分增强项" : item.conflict_type === "potential_conflict" ? "待复核差异" : "兼容差异"}
                      </span>
                      <span className="importance-tag high">{item.risk_priority}</span>
                    </div>
                    <span className="confidence">{item.resolution_status === "resolved" ? "已解决" : "待处理"}</span>
                  </div>
                  <h3>{item.topic}</h3>
                  <p>{item.description}</p>
                  <div className="strategy-grid">
                    <div><span>来源 A · 权威等级 {item.source_a_authority_level}</span><strong>{item.source_a.document}</strong></div>
                    <div><span>来源 B · 权威等级 {item.source_b_authority_level}</span><strong>{item.source_b.document}</strong></div>
                    <div><span>影响章节</span><strong>{item.affected_sections.join("、") || "不影响技术章节"}</strong></div>
                  </div>
                  <details>
                    <summary>查看两处原文</summary>
                    <blockquote>{item.source_a.text}</blockquote>
                    <blockquote>{item.source_b.text}</blockquote>
                  </details>
                  {item.conflict_type === "true_conflict" && (
                    <div className="card-actions feedback-actions">
                      <button disabled={Boolean(busy)} onClick={() => resolveConflict(item, "choose_a")}>采用 A</button>
                      <button disabled={Boolean(busy)} onClick={() => resolveConflict(item, "choose_b")}>采用 B</button>
                      <button disabled={Boolean(busy)} onClick={() => resolveConflict(item, "keep_both")}>分别响应</button>
                      <button disabled={Boolean(busy)} onClick={() => resolveConflict(item, "request_clarification")}>提交澄清</button>
                    </div>
                  )}
                </article>
              ))}
              {requirementView !== "conflicts" && Object.entries(grouped).map(([chapter, items]) => (
                <details className="requirement-group" key={chapter} open={Object.keys(grouped).length <= 3}>
                  <summary><h3>{chapter}<small>{items.length} 条同类响应事项</small></h3><span>{responseActionLabels[items[0].response_action]} · 一起归类和写入</span></summary>
                  <div className="requirement-list">
                    {items.map((item) => (
                      <article className={`requirement-card feedback-${item.feedback} ${item.scoring_impact === "score_item" ? "scoring-card" : ""}`} key={item.id}>
                        <div className="requirement-top">
                          <div className="requirement-tags">
                            <span className={`type-tag ${item.type}`}>{typeLabels[item.type]}</span>
                            <span className={`importance-tag ${item.importance}`}>{importanceLabels[item.importance]}</span>
                          </div>
                          <span className="confidence">判断置信度 {Math.round(item.classification_confidence * 100)}%</span>
                        </div>
                        <h3>{item.title}</h3>
                        <p>{item.normalized_text}</p>
                        {item.semantic_graph?.focus_summary && (
                          <details className="requirement-semantics">
                            <summary>查看业务实体与关系</summary>
                            <strong>{item.semantic_graph.focus_summary}</strong>
                            {item.semantic_graph.relations.length > 0 && <ul>{item.semantic_graph.relations.map((relation, index) => (
                              <li key={`${relation.predicate}-${index}`}>{entityLabel(item, relation.subject)} → {relation.predicate_label} → {entityLabel(item, relation.object)}</li>
                            ))}</ul>}
                            {item.semantic_graph.actions.length > 0 && <p>响应动作：{Array.from(new Set(item.semantic_graph.actions.map((action) => action.action_label))).join("、")}</p>}
                            {item.semantic_graph.constraints.length > 0 && <p>签字、盖章等仅作为办理约束：{item.semantic_graph.constraints.join("、")}</p>}
                          </details>
                        )}
                        <div className="strategy-grid">
                          <div><span>类型</span><strong>{typeLabels[item.type]}</strong></div>
                          <div><span>响应方式</span><strong>{responseActionLabels[item.response_action]}</strong></div>
                          <div><span>影响</span><strong>{scoringImpactLabels[item.scoring_impact]}</strong></div>
                          <div><span>优先级</span><strong>{item.priority}</strong></div>
                          <div><span>方案价值</span><strong>{item.proposal_value > 0 ? "★".repeat(item.proposal_value) : "不进入正文"}</strong></div>
                          <div><span>是否进入技术正文</span><strong>{item.response_action === "write_into_proposal" ? "是" : "否"}</strong></div>
                          {item.proposal_mapping && <div><span>章节</span><strong>{item.proposal_mapping}</strong></div>}
                        </div>
                        <details><summary>查看原文依据</summary><blockquote>{item.quote}</blockquote>
                          <div className="source-row">{item.sources.map((source) => <span key={source.id}>{source.filename} · {sourceLabel(source)}</span>)}</div>
                        </details>
                        <div className="card-actions feedback-actions" aria-label="人工确认">
                          <span>
                            {item.feedback === "pending"
                              ? "请选择处理方式"
                              : item.feedback === "confirmed"
                              ? "已确认当前处理"
                              : `已忽略 · ${ignoreFeedbackLabels[item.feedback as IgnoreFeedback]}`}
                          </span>
                          <button
                            className={item.feedback === "confirmed" ? "selected" : ""}
                            disabled={Boolean(busy)}
                            onClick={() => recordRequirementFeedback(item, "confirmed")}
                          >确认当前处理</button>
                          <button
                            disabled={Boolean(busy)}
                            onClick={() => updateRequirementStrategy(
                              item,
                              item.response_action === "write_into_proposal"
                                ? "compliance"
                                : "proposal",
                            )}
                          >
                            {item.response_action === "write_into_proposal"
                              ? "转为商务合规"
                              : "转为技术方案"}
                          </button>
                          <button
                            className={item.feedback !== "pending" && item.feedback !== "confirmed" ? "selected warning" : ""}
                            disabled={Boolean(busy)}
                            onClick={() => setIgnoreMenuId((current) => current === item.id ? "" : item.id)}
                          >忽略</button>
                        </div>
                        {ignoreMenuId === item.id && (
                          <div className="ignore-reasons" role="group" aria-label="选择忽略原因">
                            <strong>为什么忽略？</strong>
                            {(Object.entries(ignoreFeedbackLabels) as [IgnoreFeedback, string][]).map(([value, label]) => (
                              <button
                                key={value}
                                className={item.feedback === value ? "selected" : ""}
                                disabled={Boolean(busy)}
                                onClick={() => recordRequirementFeedback(item, value)}
                              >{label}</button>
                            ))}
                          </div>
                        )}
                      </article>
                    ))}
                  </div>
                </details>
              ))}
            </div>
          )}

          {step === "outline" && (
            <div className="outline-layout">
              {workspace?.template_outline?.length > 0 && (
                <section className="panel template-outline-panel">
                  <div>
                    <span className="panel-label">TENDER RESPONSE FORMAT</span>
                    <h3>招标文件规定的投标文件格式</h3>
                    <p>已从原文件识别 {workspace.template_outline.length} 个标题，最多保留五级层次。正式装配时以此结构为准，不由 AI 擅自改名。</p>
                  </div>
                  <ol className="template-outline-tree">
                    {workspace.template_outline.map((item) => (
                      <li key={`${item.order}-${item.title}`} data-level={item.level}>
                        <b>{item.order}</b><span>{item.title}</span><small>{item.level} 级</small>
                      </li>
                    ))}
                  </ol>
                </section>
              )}
              <div className="section-toolbar">
                <div><strong>{sections.length}</strong><span>个推荐章节</span></div>
                <p>可改名和调整顺序，不需要逐条确认要求。</p>
                <button className="primary" onClick={saveOutline}>确认目录并开始写作</button>
              </div>
              <div className="outline-list">
                {sections.map((section, index) => (
                  <article key={section.id}>
                    <b>{String(index + 1).padStart(2, "0")}</b>
                    <input value={section.title} onChange={(event) => updateChapter(index, event.target.value)} />
                    <span>映射 {section.requirement_ids.length} 条要求</span>
                    <button onClick={() => moveChapter(index, -1)} disabled={index === 0}>↑</button>
                    <button onClick={() => moveChapter(index, 1)} disabled={index === sections.length - 1}>↓</button>
                  </article>
                ))}
              </div>
            </div>
          )}

          {step === "writer" && (
            <div className="writer-layout">
              <aside className="panel writer-sidebar">
                <span className="panel-label">CHAPTERS</span>
                <h3>技术方案目录</h3>
                <button
                  className="primary"
                  disabled={Boolean(busy) || sections.length === 0}
                  onClick={generateCompleteDraft}
                >一键生成整本初稿</button>
                <p>后台按章生成和校核，断线不丢失；不会自动代替人工确认。</p>
                <div className="saved-sections">
                  {sections.map((section, index) => (
                    <button key={section.id} className={section.id === activeSectionId ? "active" : ""} onClick={() => selectSection(section)}>
                      <strong>{index + 1}. {section.title}</strong><span>{section.status === "approved" ? "已确认" : section.current_version ? "待确认" : "待生成"}</span>
                    </button>
                  ))}
                </div>
              </aside>
              <div className="editor-panel">
                {activeSection ? <>
                  <div className="editor-bar">
                    <div><strong>{activeSection.title}</strong><span>响应 {activeSection.requirement_ids.length} 条要求</span></div>
                    <div>
                      <button className="primary" onClick={() => generateSection(activeSection)}>{activeSection.current_version ? "按要求重新生成" : "生成本章"}</button>
                      {activeSection.current_version && <button className="secondary" onClick={saveSection}>保存修改</button>}
                      {activeSection.current_version && <button className="primary" onClick={approveSection}>人工确认</button>}
                    </div>
                  </div>
                  <div className="generation-instruction">
                    <label htmlFor="generation-instruction">本章微调要求（可选）</label>
                    <div className="length-controls">
                      <label>最少字数<input type="number" min={200} max={20000} value={minChapterChars} onChange={(event) => setMinChapterChars(Number(event.target.value))} /></label>
                      <label>最多字数<input type="number" min={200} max={20000} value={maxChapterChars} onChange={(event) => setMaxChapterChars(Number(event.target.value))} /></label>
                    </div>
                    <select value={caseReferenceMode} onChange={(event) => setCaseReferenceMode(event.target.value as typeof caseReferenceMode)} aria-label="历史案例参考方式">
                      <option value="balanced">综合参考多个相似案例</option>
                      <option value="closest_case">尽量贴近最相似案例</option>
                      <option value="structure_only">仅参考案例结构</option>
                      <option value="current_only">不参考历史案例</option>
                    </select>
                    <textarea
                      id="generation-instruction"
                      value={generationInstruction}
                      maxLength={1000}
                      onChange={(event) => setGenerationInstruction(event.target.value)}
                      placeholder="例如：更突出进度控制；语言简洁一些；按准备、实施、验收三个阶段展开。不能要求系统虚构企业事实。"
                    />
                    <span>{generationInstruction.length}/1000</span>
                  </div>
                  {activeSection.findings.length > 0 && <div className="findings">{activeSection.findings.map((item) => <p className="warning" key={item.id}>{item.message}</p>)}</div>}
                  <textarea
                    value={editorContent}
                    onChange={(event) => setEditorContent(event.target.value)}
                    placeholder="点击“生成本章”，系统将严格依据本章映射的技术要求撰写。"
                    disabled={!activeSection.current_version}
                  />
                </> : <div className="empty-state">请先确认推荐目录。</div>}
              </div>
            </div>
          )}

          {step === "export" && (
            <div className={`export-layout ${usesTemplateFlow ? "strict-export" : ""}`}>
              <div className="delivery-card">
                <div className="delivery-icon">W</div>
                <div><span className="panel-label">DELIVERABLE</span><h3>{workspace?.name ?? "技术方案"}</h3><p>{conversionPending ? "PDF 转换未通过结构验证，已停止后续写作，避免生成一套错误目录。" : workspace?.generation_mode === "strict_template" && sections.length === 0 ? "系统将直接在原投标文件格式中回填已匹配字段，不额外虚构技术章节。" : "系统将按目录顺序合并所有已人工确认章节，并附技术要求来源总表。"}</p></div>
                <span className={`approval ${(workspace?.generation_mode === "strict_template" && sections.length === 0) || (sections.length > 0 && sections.every((item) => item.status === "approved")) ? "ready" : ""}`}>{conversionPending ? "转换待处理" : workspace?.generation_mode === "strict_template" && sections.length === 0 ? "原格式字段待审核" : sections.length > 0 && sections.every((item) => item.status === "approved") ? "全部章节已确认" : "需逐章生成并确认"}</span>
              </div>
              <div className="panel export-actions">
                <h3>生成交付文件</h3>
                <p>一次完成来源校核、真实性检查和 Word 生成；阻断问题必须处理后才能正式导出。</p>
                {conversionPending && (
                  <div className="message error conversion-status-card">
                    <div>
                      <strong>检测到 PDF，但尚无法可靠转换</strong>
                      <p>{workspace?.template_conversion_report?.message || "转换后的 Word 未通过可编辑结构验证。"}</p>
                      <small>系统已保留原 PDF 和解析结果，且未调用目录写作引擎。请上传该文件的可编辑 DOCX 版。</small>
                    </div>
                  </div>
                )}
                {responseSupport?.manual_action_archive && workspace?.generation_mode === "planned" && (
                  <details className="manual-archive" open={responseSupport.manual_action_archive.pending > 0}>
                    <summary>
                      人工事项档案
                      <b>{responseSupport.manual_action_archive.pending} 项待处理</b>
                    </summary>
                    <p>系统集中记录需要补充到企业数据库或人工审核的内容；业务人员只审核，不在此页重复录入。</p>
                    <div>
                      {responseSupport.manual_action_archive.items.map((item) => (
                        <article key={item.key} className={item.status}>
                          <span>{item.status === "completed" ? "已完成" : "待处理"}</span>
                          <strong>{item.title}</strong>
                          <p>{item.instruction}</p>
                          <small>影响范围：{item.blocking_scope}</small>
                        </article>
                      ))}
                    </div>
                  </details>
                )}
                {workspace?.generation_mode === "strict_template" && (
                  <div className="template-fields">
                    <div className="strict-fill-workbench">
                      <section className="fill-preview-pane">
                        <header><span className="panel-label">DOCUMENT PREVIEW</span><h3>回填结果预览</h3><small>{workspace.template_filename}</small></header>
                        <WordDocumentPreview workspace={workspace} />
                      </section>
                      <section className="fill-review-pane">
                        <header><span className="panel-label">REVIEW & EXPORT</span><h3>核验实体关系并导出</h3><p>系统先识别业务实体和项目角色，再读取对应属性；人员字段不能直接输入姓名，只允许审核或建立角色绑定。</p></header>
                        <div className="font-fidelity-note">
                          <b>已自动继承原模板字体</b>
                          <span>{workspace.template_fonts?.length ? workspace.template_fonts.join("、") : "使用原段落样式"}</span>
                          <small>回填字段和生成正文均继承所在模板样式，不再强制替换为系统默认字体。</small>
                        </div>
                        <div className="case-library-note"><b>{workspace.case_library_name}：{workspace.case_library_count} 组真实案例</b><span>机构私有；系统自动匹配，业务人员只做角色绑定与人工确认来源。</span></div>
                        {(workspace.template_actions ?? []).length > 0 && <div className="case-library-note"><b>已识别 {(workspace.template_actions ?? []).length} 项签章动作</b><span>{workspace.template_actions.map((action) => action.display_name).filter((value, index, values) => values.indexOf(value) === index).join("、")}；动作不再冒充待填文字。</span></div>}
                        {missingTemplateDecisions.length > 0 ? <p className="template-field-warning">企业资料库缺少 {missingTemplateDecisions.length} 项资料。系统保留空位，不允许 AI 猜写。</p> : <p className="template-field-ready">全部字段已匹配，请审核后导出。</p>}
                        <div className="fill-decision-list">
                          {(workspace.template_field_decisions ?? []).map((item) => (
                            <article key={item.field_key} className={`fill-decision ${item.status.toLowerCase()}`}>
                              <div><strong>{item.display_name || item.label}</strong><span>{fillStatusLabels[item.status]}</span></div>
                              {editingFieldKey === item.field_key ? (
                                <div className="field-edit-form">
                                  <input aria-label={`修改${item.label}`} maxLength={500} value={editingFieldValue} onChange={(event) => setEditingFieldValue(event.target.value)} autoFocus />
                                  <div>
                                    <button className="secondary compact" disabled={Boolean(busy) || !editingFieldValue.trim()} onClick={() => reviewTemplateField(item.field_key, "confirm", editingFieldValue.trim())}>保存并确认</button>
                                    <button className="text-button" disabled={Boolean(busy)} onClick={() => { setEditingFieldKey(""); setEditingFieldValue(""); }}>取消</button>
                                  </div>
                                </div>
                              ) : <p>{item.value || "尚未提供"}</p>}
                              <small>原模板槽位：{item.label} · 应填：{item.expected_value_type_label} · {item.type_validation === "passed" ? "类型校验已通过" : "未获得符合类型的值"}</small>
                              {item.semantic_field && (
                                <div className="entity-resolution-card">
                                  <div><span>识别结果</span><strong>{item.display_name || (item.expected_role_label ? `${item.expected_role_label}${item.expected_value_type_label}` : item.label)}</strong></div>
                                  {(item.relation_path ?? []).length > 0 && <div><span>实际取值关系</span><strong>{item.relation_path.join(" → ")}</strong></div>}
                                  {item.subject_organization && <div><span>所属主体</span><strong>{item.subject_organization}</strong></div>}
                                  {item.expected_role_label && <div><span>目标角色</span><strong>{item.expected_role_label}</strong></div>}
                                  {item.project_name && item.expected_role !== "LEGAL_REPRESENTATIVE" && <div><span>当前项目</span><strong>{item.project_name}</strong></div>}
                                  <div><span>当前状态</span><strong>{item.binding_status === "resolved" ? "已确定唯一实体和角色" : item.reason}</strong></div>
                                  {(item.required_actions ?? []).length > 0 && <div><span>随附动作</span><strong>{item.required_actions.join("、")}</strong></div>}
                                  {item.slot?.surrounding_text && <details><summary>查看槽位判断上下文</summary><blockquote>{item.slot.surrounding_text}</blockquote></details>}
                                  {(item.match_path ?? []).length > 0 && <details><summary>查看匹配路径</summary><ol>{item.match_path.map((step, index) => <li key={`${step}-${index}`}>{step}</li>)}</ol></details>}
                                  {(item.entity_candidates ?? []).length > 0 && item.binding_status !== "resolved" && (
                                    <div className="entity-candidates">
                                      <span>候选人员</span>
                                      {item.entity_candidates.map((candidate) => (
                                        <article key={candidate.person_id}>
                                          <div><strong>{candidate.name}</strong><small>{candidate.title || "职务待核验"}</small></div>
                                          <p>{candidate.match_basis}</p>
                                          {(candidate.source_document || candidate.source_location) && <small>依据：{candidate.source_document || "已核验人员库"}{candidate.source_location ? ` · ${candidate.source_location}` : ""}</small>}
                                          <button className="secondary compact" disabled={Boolean(busy) || !item.expected_role} onClick={() => bindEntityRole(item, candidate)}>选择并建立角色绑定</button>
                                        </article>
                                      ))}
                                    </div>
                                  )}
                                  {item.expected_entity_type === "Person" && item.binding_status !== "resolved" && (item.entity_candidates ?? []).length === 0 && <p className="template-field-warning">当前没有可选的已核验人员，需要先在受控人员库新增并核验。</p>}
                                </div>
                              )}
                              <small>{item.reason}</small>
                              {(item.source_reference || item.evidence_title) && <small>来源：{visibleEvidenceSource(item)} · {visibleEvidenceLocation(item)}</small>}
                              {(item.evidence_title || item.value) && <button className="evidence-open-button" onClick={() => setEvidenceItem(item)}>查看原文定位</button>}
                              {editingFieldKey !== item.field_key && <div className="field-review-actions">
                                {item.status === "REVIEW_REQUIRED" && item.value && <button className="secondary compact" disabled={Boolean(busy)} onClick={() => reviewTemplateField(item.field_key, "confirm")}>确认该字段</button>}
                                {item.status === "AUTO_FILL" && item.source_type === "manual_verified" && <button className="text-button" disabled={Boolean(busy)} onClick={() => reviewTemplateField(item.field_key, "reset")}>重新审核</button>}
                              </div>}
                            </article>
                          ))}
                        </div>
                        {!exportItem && <button className="primary strict-export-button" disabled={Boolean(busy)} onClick={approveTemplateAndExport}>审核已匹配内容并生成原格式 Word</button>}
                      </section>
                    </div>
                  </div>
                )}
                {proposalReview && (
                  <div className="review-summary ready">
                    <strong>{proposalReview.overall.recommended_for_delivery ? "校核完成" : "校核完成，请留意建议"}</strong>
                    <span>需求覆盖 {(proposalReview.overall.requirement_coverage_rate * 100).toFixed(0)}%</span>
                    <span>评分点覆盖 {(proposalReview.overall.scoring_coverage_rate * 100).toFixed(0)}%</span>
                    <span>来源追溯 {(proposalReview.overall.traceability_rate * 100).toFixed(0)}%</span>
                    <span>重点提醒 {proposalReview.overall.blocking_risk_count}</span>
                    <span>分类质量 {(proposalReview.classification_quality.quality_rate * 100).toFixed(0)}%</span>
                    <span>低置信分类 {proposalReview.classification_quality.low_confidence_count}</span>
                    <span>未映射章节 {proposalReview.classification_quality.unmapped_count}</span>
                    <span>分类冲突 {proposalReview.classification_quality.conflict_count}</span>
                    <a href={`${API_BASE}/workspaces/${workspace?.id}/review/download?format=md`}>下载可读 Review</a>
                    <a href={`${API_BASE}/workspaces/${workspace?.id}/review/download?format=json`}>下载 JSON</a>
                  </div>
                )}
                {responseSupport && responseSupport.traceability.requirements.length > 0 && (
                  <details className="traceability-map">
                    <summary>查看 AI 响应与原文定位</summary>
                    {responseSupport.traceability.requirements.map((item) => (
                      <article key={item.requirement_id}>
                        <strong>{item.title}</strong>
                        <span>{item.generated_sections.length > 0 ? `AI 已响应：${item.generated_sections.join("、")}` : "未进入技术方案正文"}</span>
                        <details>
                          <summary>打开采购原文</summary>
                          <blockquote>{item.source_text}</blockquote>
                          <div className="source-row">{item.sources.map((source) => <span key={source.id}>{source.filename} · {sourceLabel(source)}</span>)}</div>
                        </details>
                      </article>
                    ))}
                    <details className="generated-trace-list">
                      <summary>查看 AI 正文逐段来源</summary>
                      {responseSupport.traceability.generated_paragraphs.map((item) => (
                        <article key={`${item.section_id}-${item.paragraph_index}`}>
                          <strong>{item.section_title} · 第 {item.paragraph_index + 1} 段</strong>
                          <p>{item.generated_text}</p>
                          {item.sources.length === 0 ? <span>未直接匹配输入证据，需人工复核</span> : item.sources.map((source, index) => (
                            <details key={`${source.source_title}-${index}`}>
                              <summary>{source.source_title} · {source.verification_status === "verified" ? "已核验" : "待核验"}</summary>
                              {source.source_excerpt && <blockquote>{source.source_excerpt}</blockquote>}
                              {source.source_location && <span>{source.source_location}</span>}
                            </details>
                          ))}
                        </article>
                      ))}
                    </details>
                  </details>
                )}
                {workspace?.generation_mode === "planned" && <button className="primary large" disabled={!sections.length || sections.some((item) => item.status !== "approved")} onClick={createExport}>校核并生成 Word</button>}
                {exportItem?.status === "succeeded" && workspace && (
                  <a className="download-button" href={`${API_BASE}/workspaces/${workspace.id}/exports/${exportItem.id}/download`}>下载 {exportItem.filename}</a>
                )}
              </div>
            </div>
          )}
        </section>
      </div>
      {evidenceItem && (
        <div className="evidence-modal-backdrop" role="presentation" onMouseDown={() => setEvidenceItem(null)}>
          <section className="evidence-modal" role="dialog" aria-modal="true" aria-labelledby="evidence-modal-title" onMouseDown={(event) => event.stopPropagation()}>
            <header><div><span className="panel-label">SOURCE EVIDENCE</span><h3 id="evidence-modal-title">{evidenceItem.label} · 原文依据</h3></div><button aria-label="关闭原文依据" onClick={() => setEvidenceItem(null)}>×</button></header>
            <dl><div><dt>来源文件</dt><dd>{visibleEvidenceSource(evidenceItem)}</dd></div><div><dt>原文位置</dt><dd>{visibleEvidenceLocation(evidenceItem)}</dd></div>{evidenceItem.evidence_match_count > 1 && <div><dt>一致匹配</dt><dd>{evidenceItem.evidence_match_count} 处</dd></div>}{(evidenceItem.evidence_alternatives ?? []).length > 0 && <div><dt>其他候选</dt><dd>{evidenceItem.evidence_alternatives.join("、")}</dd></div>}</dl>
            <div className="evidence-context"><strong>原文上下文</strong><blockquote>{highlightedEvidence(evidenceItem.evidence_excerpt || evidenceItem.value || "当前来源记录暂无可展示的上下文。", evidenceItem.value)}</blockquote></div>
            <p>黄色标记为本次自动匹配内容。仅展示该项目已获授权的原文片段，不暴露内部路径和系统字段。</p>
          </section>
        </div>
      )}
    </main>
  );
}
