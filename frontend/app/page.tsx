"use client";

import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useState } from "react";

type Step = "upload" | "requirements" | "outline" | "writer" | "export";
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
  type: "technical_requirement" | "scoring_requirement" | "commercial_requirement" | "qualification_requirement" | "delivery_requirement" | "compliance_requirement" | "format_requirement";
  title: string;
  normalized_text: string;
  quote: string;
  importance: "critical" | "high" | "medium" | "low";
  proposal_relevance: "high" | "medium" | "low";
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
  sources: Source[];
};
type IgnoreFeedback = Exclude<Requirement["feedback"], "pending" | "confirmed">;

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
  outline: SectionItem[];
  estimated_remaining_seconds_low: number | null;
  estimated_remaining_seconds_high: number | null;
  estimate_sample_count: number;
  estimate_basis: string;
  processing_error_code: string | null;
  processing_error_message: string | null;
  processing_retryable: boolean;
  model_calls_used: number;
  model_calls_limit: number;
  model_tokens_used: number;
  model_tokens_limit: number;
};
type ExportItem = { id: string; status: string; filename?: string | null };
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
const typeLabels: Record<Requirement["type"], string> = {
  technical_requirement: "技术要求",
  scoring_requirement: "评分要求",
  commercial_requirement: "商务要求",
  qualification_requirement: "资格要求",
  delivery_requirement: "交付要求",
  compliance_requirement: "合规要求",
  format_requirement: "格式要求",
};
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
  const [requirementView, setRequirementView] = useState<"proposal" | "compliance">("proposal");
  const [ignoreMenuId, setIgnoreMenuId] = useState("");
  const [sections, setSections] = useState<SectionItem[]>([]);
  const [activeSectionId, setActiveSectionId] = useState("");
  const [editorContent, setEditorContent] = useState("");
  const [generationInstruction, setGenerationInstruction] = useState("");
  const [exportItem, setExportItem] = useState<ExportItem | null>(null);
  const [proposalReview, setProposalReview] = useState<ProposalReview | null>(null);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

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
      const importanceDelta = importanceRank[left.importance] - importanceRank[right.importance];
      if (importanceDelta) return importanceDelta;
      return Number(right.proposal_relevance === "high") - Number(left.proposal_relevance === "high");
    });
    const groups = sorted.reduce<Record<string, Requirement[]>>((result, item) => {
      const chapter = requirementView === "compliance"
        ? typeLabels[item.type]
        : item.proposal_chapter ?? item.target_chapter ?? "其他技术要求";
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
  const progress = workspace ? Math.max(20, (steps.findIndex((item) => item.id === step) + 1) * 20) : 0;

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

  function openCompletedWorkspace(completed: Workspace, message?: string) {
    setWorkspace(completed);
    setRequirements(completed.technical_requirements);
    setRequirementView("proposal");
    setSections(completed.outline);
    setActiveSectionId(completed.outline[0]?.id ?? "");
    setEditorContent(completed.outline[0]?.current_version?.content ?? "");
    setStep("requirements");
    setNotice(
      message
      ?? `处理完成，已提取 ${completed.technical_requirements.length} 条技术写作要点。`,
    );
  }

  async function waitForWorkspace(workspaceId: string, initial: Workspace) {
    let completed = initial;
    let consecutiveNetworkErrors = 0;
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
        if (consecutiveNetworkErrors >= 5) {
          throw new Error("网络连接暂时中断，请保持当前页面并稍后重试。");
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
      const completed = await waitForWorkspace(created.id, created);
      openCompletedWorkspace(
        completed,
        `已识别《${completed.document?.filename}》，提取 ${completed.technical_requirements.length} 条技术写作要点。`,
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
      openCompletedWorkspace(completed, "已从中断位置继续并完成目录规划。");
    });
  }

  async function showRequirements(view: "proposal" | "compliance") {
    if (!workspace) return;
    await run(view === "proposal" ? "正在读取响应事项" : "正在读取合规提醒", async () => {
      const items = await request<Requirement[]>(`/workspaces/${workspace.id}/requirements?view=${view}`);
      setRequirements(items);
      setRequirementView(view);
      setNotice(view === "compliance" && items.length === 0 ? "没有发现额外合规提醒。" : "");
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
      const generated = await request<SectionItem>(
        `/workspaces/${workspace.id}/sections/${section.id}/generate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            instruction: generationInstruction.trim() || null,
          }),
        },
      );
      setSections((items) => items.map((item) => item.id === generated.id ? generated : item));
      setActiveSectionId(generated.id);
      setEditorContent(generated.current_version?.content ?? "");
      setGenerationInstruction("");
      setNotice("章节已生成，请人工检查并补充企业真实信息。");
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
      setExportItem(created);
      setProposalReview(review);
      setNotice(
        review.overall.recommended_for_delivery
          ? "校核完成，Word 文件已经生成。"
          : `Word 已生成，有 ${review.overall.blocking_risk_count} 项建议人工留意。`,
      );
    });
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
            {steps.map((item, index) => (
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
              <h2>{steps.find((item) => item.id === step)?.title}</h2>
              <p>系统按固定步骤处理，不会自由对话或无限循环。</p>
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
              <h3>上传招标文件，直接生成技术方案框架</h3>
              <p>无需先建项目。系统会自动判断文件是否有效，解析技术要求与评分点，并推荐写作目录。</p>
              <label className={`upload-zone hero ${busy ? "disabled" : ""}`}>
                <input type="file" accept=".pdf,.docx" disabled={Boolean(busy)} onChange={upload} />
                <strong>选择 PDF 或 DOCX 招标文件</strong>
                <span>文件仅在机构私有环境中处理</span>
              </label>
              <div className="pipeline">
                {["有效性检查", "文档解析", "技术要求提取", "质量复核", "目录规划"].map((item, index) => (
                  <div key={item}><b>{index + 1}</b><span>{item}</span></div>
                ))}
              </div>
            </div>
          )}

          {step === "requirements" && (
            <div className="requirement-layout">
              <div className="section-toolbar">
                <div><strong>{requirements.length}</strong><span>条技术写作要点</span></div>
                <div><strong>{requirements.filter((item) => item.scoring_impact === "score_item").length}</strong><span>个评分事项</span></div>
                <div><strong>{feedbackSummary.confirmed}</strong><span>条已确认需要</span></div>
                <button className="primary" disabled={Boolean(busy)} onClick={() => setStep("outline")}>下一步：查看推荐目录</button>
              </div>
              <div className="requirement-tabs" role="tablist" aria-label="要求分类">
                <button
                  type="button"
                  role="tab"
                  aria-selected={requirementView === "proposal"}
                  className={requirementView === "proposal" ? "active" : ""}
                  disabled={Boolean(busy)}
                  onClick={() => showRequirements("proposal")}
                >
                  技术方案要点 <span>{requirementView === "proposal" ? requirements.length : workspace?.technical_requirements.length ?? 0}</span>
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={requirementView === "compliance"}
                  className={requirementView === "compliance" ? "active" : ""}
                  disabled={Boolean(busy)}
                  onClick={() => showRequirements("compliance")}
                >
                  合规要求 <span>{workspace?.compliance_reminder_count ?? 0}</span>
                </button>
              </div>
              <div className="requirement-guidance">
                <div>
                  <strong>{requirementView === "proposal" ? "优先确认影响技术方案的要求" : "集中查看资格、商务及其他合规提醒"}</strong>
                  <span>关键和重要内容优先展示，“其他”放在最后；无需逐条确认即可继续。</span>
                </div>
                <div className="feedback-summary" aria-label="人工确认进度">
                  <span><b>{feedbackSummary.pending}</b> 待判断</span>
                  <span><b>{feedbackSummary.ignored}</b> 已忽略</span>
                  {feedbackSummary.issues > 0 && <span className="warning"><b>{feedbackSummary.issues}</b> 条问题反馈</span>}
                </div>
              </div>
              {Object.entries(grouped).map(([chapter, items]) => (
                <section className="requirement-group" key={chapter}>
                  <h3>{chapter}<small>{items.length} 条</small></h3>
                  <div className="requirement-list">
                    {items.map((item) => (
                      <article className={`requirement-card feedback-${item.feedback} ${item.scoring_impact === "score_item" ? "scoring-card" : ""}`} key={item.id}>
                        <div className="requirement-top">
                          <div className="requirement-tags">
                            <span className={`type-tag ${item.type}`}>{typeLabels[item.type]}</span>
                            <span className={`importance-tag ${item.importance}`}>{importanceLabels[item.importance]}</span>
                          </div>
                          <span className="confidence">{item.proposal_relevance === "high" ? "重点响应" : "建议响应"}</span>
                        </div>
                        <h3>{item.title}</h3>
                        <p>{item.normalized_text}</p>
                        <details><summary>查看原文依据</summary><blockquote>{item.quote}</blockquote>
                          <div className="source-row">{item.sources.map((source) => <span key={source.id}>{source.filename} · {sourceLabel(source)}</span>)}</div>
                        </details>
                        <div className="card-actions feedback-actions" aria-label="人工确认">
                          <span>
                            {item.feedback === "pending"
                              ? "请选择处理方式"
                              : item.feedback === "confirmed"
                              ? "已写入方案"
                              : `已忽略 · ${ignoreFeedbackLabels[item.feedback as IgnoreFeedback]}`}
                          </span>
                          <button
                            className={item.feedback === "confirmed" ? "selected" : ""}
                            disabled={Boolean(busy)}
                            onClick={() => recordRequirementFeedback(item, "confirmed")}
                          >写入方案</button>
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
                </section>
              ))}
            </div>
          )}

          {step === "outline" && (
            <div className="outline-layout">
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
            <div className="export-layout">
              <div className="delivery-card">
                <div className="delivery-icon">W</div>
                <div><span className="panel-label">DELIVERABLE</span><h3>{workspace?.name ?? "技术方案"}</h3><p>系统将按目录顺序合并所有已人工确认章节，并附技术要求来源总表。</p></div>
                <span className={`approval ${sections.length > 0 && sections.every((item) => item.status === "approved") ? "ready" : ""}`}>{sections.length > 0 && sections.every((item) => item.status === "approved") ? "全部章节已确认" : "需逐章生成并确认"}</span>
              </div>
              <div className="panel export-actions">
                <h3>生成交付文件</h3>
                <p>一次完成来源校核、真实性检查、自动清理和 Word 生成；检查结果仅作提醒，不会阻断导出。</p>
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
                <button className="primary large" disabled={!sections.length || sections.some((item) => item.status !== "approved")} onClick={createExport}>校核并生成 Word</button>
                {exportItem?.status === "succeeded" && workspace && (
                  <a className="download-button" href={`${API_BASE}/workspaces/${workspace.id}/exports/${exportItem.id}/download`}>下载 {exportItem.filename}</a>
                )}
              </div>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
