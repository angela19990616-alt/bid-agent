"use client";

import { ChangeEvent, useCallback, useMemo, useState } from "react";

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
  type: "technical" | "scoring" | "delivery" | "qualification" | "compliance" | "commercial";
  title: string;
  normalized_text: string;
  quote: string;
  proposal_relevance: "high" | "medium" | "low";
  target_chapter: string | null;
  need_generation: boolean;
  sources: Source[];
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
};
type ExportItem = { id: string; status: string; filename?: string | null };

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1").replace(/\/$/, "");
const steps: Array<{ id: Step; title: string; subtitle: string }> = [
  { id: "upload", title: "上传文件", subtitle: "自动识别与解析" },
  { id: "requirements", title: "技术要点", subtitle: "要求与评分点" },
  { id: "outline", title: "推荐目录", subtitle: "确认章节结构" },
  { id: "writer", title: "章节写作", subtitle: "生成、编辑、校核" },
  { id: "export", title: "导出 Word", subtitle: "交付技术方案" },
];
const typeLabels: Record<Requirement["type"], string> = {
  technical: "技术要求",
  scoring: "技术评分点",
  delivery: "交付与实施",
  qualification: "资格提醒",
  compliance: "合规提醒",
  commercial: "商务提醒",
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

export default function Home() {
  const [step, setStep] = useState<Step>("upload");
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [sections, setSections] = useState<SectionItem[]>([]);
  const [activeSectionId, setActiveSectionId] = useState("");
  const [editorContent, setEditorContent] = useState("");
  const [exportItem, setExportItem] = useState<ExportItem | null>(null);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const activeSection = sections.find((item) => item.id === activeSectionId);
  const grouped = useMemo(() => {
    return requirements.reduce<Record<string, Requirement[]>>((result, item) => {
      const chapter = item.target_chapter ?? "其他技术要求";
      result[chapter] = [...(result[chapter] ?? []), item];
      return result;
    }, {});
  }, [requirements]);
  const progress = workspace ? Math.max(20, (steps.findIndex((item) => item.id === step) + 1) * 20) : 0;

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
      let completed = created;
      for (let attempt = 0; attempt < 180 && completed.status !== "outline_ready"; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        completed = await request<Workspace>(`/workspaces/${created.id}`);
        setWorkspace(completed);
        if (completed.status === "draft") {
          throw new Error("文件解析或技术要求提取失败，请检查文件后重试。");
        }
      }
      if (completed.status !== "outline_ready") {
        throw new Error("处理时间较长，请稍后重新打开该方案查看结果。");
      }
      setRequirements(completed.technical_requirements);
      setSections(completed.outline);
      setActiveSectionId(completed.outline[0]?.id ?? "");
      setEditorContent(completed.outline[0]?.current_version?.content ?? "");
      setStep("requirements");
      setNotice(`已识别《${completed.document?.filename}》，提取 ${completed.technical_requirements.length} 条技术写作要点。`);
    });
  }

  async function showCompliance() {
    if (!workspace) return;
    await run("正在读取合规提醒", async () => {
      const items = await request<Requirement[]>(`/workspaces/${workspace.id}/requirements?view=compliance`);
      setNotice(items.length ? items.map((item) => item.title).slice(0, 6).join("；") : "没有发现额外合规提醒。");
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
      const saved = await request<SectionItem[]>(`/workspaces/${workspace.id}/outline`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chapters: sections.map((item) => ({
            title: item.title,
            requirement_ids: item.requirement_ids,
          })),
        }),
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
  }

  async function generateSection(section: SectionItem) {
    if (!workspace) return;
    await run(`正在生成《${section.title}》`, async () => {
      const generated = await request<SectionItem>(
        `/workspaces/${workspace.id}/sections/${section.id}/generate`,
        { method: "POST" },
      );
      setSections((items) => items.map((item) => item.id === generated.id ? generated : item));
      setActiveSectionId(generated.id);
      setEditorContent(generated.current_version?.content ?? "");
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
    await run("正在生成 Word", async () => {
      const created = await request<ExportItem>(`/workspaces/${workspace.id}/exports`, {
        method: "POST",
      });
      setExportItem(created);
      setNotice("Word 文件已经生成。");
    });
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
            <p>通过有效性、质量、重复和权限检查的文件，仅进入本机构私有知识库用于后续 RAG 检索，不用于公共模型训练。</p>
          </div>
        </aside>

        <section className="stage">
          <div className="stage-header">
            <div>
              <span className="eyebrow">CONTROLLED PROPOSAL WORKFLOW</span>
              <h2>{steps.find((item) => item.id === step)?.title}</h2>
              <p>系统按固定步骤处理，不会自由对话或无限循环。</p>
            </div>
            {busy && <div className="busy-pill"><i />{busy}</div>}
          </div>
          {error && <div className="message error">{error}</div>}
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
                <div><strong>{requirements.filter((item) => item.type === "scoring").length}</strong><span>个技术评分点</span></div>
                <button className="secondary" onClick={showCompliance}>查看 {workspace?.compliance_reminder_count ?? 0} 条合规提醒</button>
                <button className="primary" onClick={() => setStep("outline")}>查看推荐目录</button>
              </div>
              {Object.entries(grouped).map(([chapter, items]) => (
                <section className="requirement-group" key={chapter}>
                  <h3>{chapter}<small>{items.length} 条</small></h3>
                  <div className="requirement-list">
                    {items.map((item) => (
                      <article className={`requirement-card ${item.type === "scoring" ? "scoring-card" : ""}`} key={item.id}>
                        <div className="requirement-top">
                          <span className={`type-tag ${item.type}`}>{typeLabels[item.type]}</span>
                          <span className="confidence">{item.proposal_relevance === "high" ? "重点响应" : "建议响应"}</span>
                        </div>
                        <h3>{item.title}</h3>
                        <p>{item.normalized_text}</p>
                        <details><summary>查看原文依据</summary><blockquote>{item.quote}</blockquote>
                          <div className="source-row">{item.sources.map((source) => <span key={source.id}>{source.filename} · {sourceLabel(source)}</span>)}</div>
                        </details>
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
                      {!activeSection.current_version && <button className="primary" onClick={() => generateSection(activeSection)}>生成本章</button>}
                      {activeSection.current_version && <button className="secondary" onClick={saveSection}>保存修改</button>}
                      {activeSection.current_version && <button className="primary" onClick={approveSection}>人工确认</button>}
                    </div>
                  </div>
                  {activeSection.findings.length > 0 && <div className="findings">{activeSection.findings.map((item) => <p className={item.severity} key={item.id}>{item.message}</p>)}</div>}
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
                <p>Word 中包含正文、响应要求和原文来源，便于复核。</p>
                <button className="primary large" disabled={!sections.length || sections.some((item) => item.status !== "approved")} onClick={createExport}>生成整本 Word</button>
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
