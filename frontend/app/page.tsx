"use client";

import { ChangeEvent, useCallback, useEffect, useMemo, useState } from "react";

type Step = "project" | "requirements" | "writer" | "export";
type Project = { id: string; name: string; status: string };
type DocumentItem = {
  id: string;
  filename: string;
  status: string;
  source_count: number;
  error_message?: string | null;
};
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
  importance: "low" | "medium" | "high";
  confidence: number;
  status: "pending" | "confirmed" | "rejected";
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
  requirement_ids: string[];
  current_version: SectionVersion | null;
  findings: Array<{ id: string; severity: string; message: string }>;
};
type ExportItem = {
  id: string;
  status: string;
  filename?: string | null;
};

const API_BASE =
  (process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1").replace(
    /\/$/,
    "",
  );

const steps: Array<{ id: Step; number: string; title: string; subtitle: string }> = [
  { id: "project", number: "01", title: "项目材料", subtitle: "创建、上传、解析" },
  { id: "requirements", number: "02", title: "招标要求", subtitle: "提取、溯源、确认" },
  { id: "writer", number: "03", title: "技术方案", subtitle: "单章节生成与编辑" },
  { id: "export", number: "04", title: "导出结果", subtitle: "确认并下载 Word" },
];

const typeLabels: Record<Requirement["type"], string> = {
  technical: "技术要求",
  scoring: "评分点",
  delivery: "交付要求",
  qualification: "资格约束",
  compliance: "响应文件规范",
  commercial: "报价与商务",
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
  if (source.locator.kind === "page") {
    return `原文位置：第 ${source.locator.page} 页`;
  }
  const start = source.locator.paragraph_start;
  const end = source.locator.paragraph_end;
  return `原文位置：第 ${start === end ? start : `${start}-${end}`} 段`;
}

export default function Home() {
  const [step, setStep] = useState<Step>("project");
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [projectName, setProjectName] = useState("");
  const [newProjectName, setNewProjectName] = useState("");
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [sections, setSections] = useState<SectionItem[]>([]);
  const [sectionTitle, setSectionTitle] = useState("项目实施方案");
  const [selectedRequirementIds, setSelectedRequirementIds] = useState<string[]>([]);
  const [activeSectionId, setActiveSectionId] = useState("");
  const [editorContent, setEditorContent] = useState("");
  const [exportItem, setExportItem] = useState<ExportItem | null>(null);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const activeSection = sections.find((item) => item.id === activeSectionId);
  const confirmed = requirements.filter((item) => item.status === "confirmed");

  const progress = useMemo(() => {
    if (exportItem?.status === "succeeded") return 100;
    if (activeSection?.status === "approved") return 88;
    if (activeSection?.current_version) return 72;
    if (confirmed.length) return 52;
    if (documents.some((item) => item.status === "parsed")) return 30;
    if (projectId) return 12;
    return 0;
  }, [activeSection, confirmed.length, documents, exportItem, projectId]);

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

  const refreshProject = useCallback(async (id: string) => {
    const [documentList, requirementList, sectionList] = await Promise.all([
      request<DocumentItem[]>(`/projects/${id}/documents`),
      request<Requirement[]>(`/projects/${id}/requirements`),
      request<SectionItem[]>(`/projects/${id}/sections`),
    ]);
    setDocuments(documentList);
    setRequirements(requirementList);
    setSections(sectionList);
    const latest = sectionList[0];
    if (latest) {
      setActiveSectionId(latest.id);
      setEditorContent(latest.current_version?.content ?? "");
    }
  }, []);

  useEffect(() => {
    run("正在加载项目", async () => {
      const items = await request<Project[]>("/projects");
      setProjects(items);
      if (items[0]) {
        setProjectId(items[0].id);
        setProjectName(items[0].name);
        await refreshProject(items[0].id);
      }
    });
  }, [refreshProject, run]);

  async function createProject() {
    const name = newProjectName.trim();
    if (!name) {
      setError("请先填写项目名称。");
      return;
    }
    await run("正在创建项目", async () => {
      const created = await request<Project>("/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      setProjects((items) => [created, ...items]);
      setProjectId(created.id);
      setProjectName(created.name);
      setDocuments([]);
      setRequirements([]);
      setSections([]);
      setNewProjectName("");
      setNotice("项目已创建，可以上传招标文件。");
    });
  }

  async function chooseProject(id: string) {
    const project = projects.find((item) => item.id === id);
    if (!project) return;
    setProjectId(id);
    setProjectName(project.name);
    setExportItem(null);
    await run("正在打开项目", () => refreshProject(id));
  }

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !projectId) return;
    await run("正在解析文件", async () => {
      const form = new FormData();
      form.append("file", file);
      const document = await request<DocumentItem>(
        `/projects/${projectId}/documents`,
        { method: "POST", body: form },
      );
      setDocuments((items) => [document, ...items]);
      setNotice(`《${document.filename}》解析完成，共 ${document.source_count} 个来源片段。`);
    });
  }

  async function extractRequirements() {
    const parsedIds = documents
      .filter((item) => item.status === "parsed")
      .map((item) => item.id);
    if (!parsedIds.length) {
      setError("请先上传并成功解析招标文件。");
      return;
    }
    await run("正在提取要求", async () => {
      const result = await request<{ created_count: number }>(
        `/projects/${projectId}/requirements/extract`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ document_ids: parsedIds }),
        },
      );
      const items = await request<Requirement[]>(
        `/projects/${projectId}/requirements`,
      );
      setRequirements(items);
      setSelectedRequirementIds(
        items.filter((item) => item.status === "confirmed").map((item) => item.id),
      );
      setStep("requirements");
      setNotice(`已新增 ${result.created_count} 条候选要求，请人工核对原文。`);
    });
  }

  async function setRequirementStatus(item: Requirement, status: Requirement["status"]) {
    await run("正在保存要求", async () => {
      const updated = await request<Requirement>(
        `/projects/${projectId}/requirements/${item.id}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status }),
        },
      );
      setRequirements((items) =>
        items.map((current) => (current.id === updated.id ? updated : current)),
      );
      setSelectedRequirementIds((ids) =>
        status === "confirmed"
          ? Array.from(new Set([...ids, item.id]))
          : ids.filter((id) => id !== item.id),
      );
    });
  }

  async function createAndGenerateSection() {
    const ids = selectedRequirementIds.filter((id) =>
      confirmed.some((item) => item.id === id),
    );
    if (!ids.length) {
      setError("请至少选择一条已确认要求。");
      return;
    }
    await run("正在生成章节", async () => {
      const created = await request<SectionItem>(
        `/projects/${projectId}/sections`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: sectionTitle, requirement_ids: ids }),
        },
      );
      const generated = await request<SectionItem>(
        `/projects/${projectId}/sections/${created.id}/generate`,
        { method: "POST" },
      );
      setSections((items) => [generated, ...items]);
      setActiveSectionId(generated.id);
      setEditorContent(generated.current_version?.content ?? "");
      setStep("writer");
      setNotice("章节已生成并自动校核，请人工编辑确认。");
    });
  }

  async function saveSection() {
    if (!activeSection?.current_version) return;
    await run("正在保存章节", async () => {
      const saved = await request<SectionItem>(
        `/projects/${projectId}/sections/${activeSection.id}/content`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            base_version_id: activeSection.current_version?.id,
            content: editorContent,
          }),
        },
      );
      setSections((items) =>
        items.map((item) => (item.id === saved.id ? saved : item)),
      );
      setNotice(`已保存第 ${saved.current_version?.version_no} 版。`);
    });
  }

  async function approveSection() {
    if (!activeSection) return;
    await run("正在确认章节", async () => {
      const approved = await request<SectionItem>(
        `/projects/${projectId}/sections/${activeSection.id}/approve`,
        { method: "POST" },
      );
      setSections((items) =>
        items.map((item) => (item.id === approved.id ? approved : item)),
      );
      setStep("export");
      setNotice("章节已人工确认，可以导出 Word。");
    });
  }

  async function createExport() {
    if (!activeSection?.current_version) return;
    await run("正在生成 Word", async () => {
      const result = await request<ExportItem>(`/projects/${projectId}/exports`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          section_id: activeSection.id,
          section_version_id: activeSection.current_version?.id,
          format: "docx",
        }),
      });
      setExportItem(result);
      setNotice("Word 已生成，可以下载。");
    });
  }

  return (
    <main className="workbench">
      <header className="masthead">
        <div className="brand-lockup">
          <span className="brand-seal">岳</span>
          <div>
            <small>DAYUE · BID AGENT</small>
            <h1>标书智能工作台</h1>
          </div>
        </div>
        <div className="project-switcher">
          <span>当前项目</span>
          <select value={projectId} onChange={(event) => chooseProject(event.target.value)}>
            <option value="">请选择项目</option>
            {projects.map((item) => (
              <option key={item.id} value={item.id}>{item.name}</option>
            ))}
          </select>
          <b className="live-badge">真实数据</b>
        </div>
      </header>

      <div className="workspace">
        <aside className="rail">
          <div className="progress-box">
            <span>项目进度</span><strong>{progress}%</strong>
            <i><em style={{ width: `${progress}%` }} /></i>
          </div>
          <nav aria-label="项目流程">
            {steps.map((item) => (
              <button
                key={item.id}
                className={step === item.id ? "active" : ""}
                onClick={() => setStep(item.id)}
              >
                <span>{item.number}</span>
                <div><strong>{item.title}</strong><small>{item.subtitle}</small></div>
              </button>
            ))}
          </nav>
          <div className="privacy-note">
            <strong>安全提示</strong>
            <p>文件和密钥不会显示在对话中；所有生成内容须人工确认。</p>
          </div>
        </aside>

        <section className="stage">
          <div className="stage-header">
            <div>
              <span className="eyebrow">BID PRODUCTION FLOW</span>
              <h2>{steps.find((item) => item.id === step)?.title}</h2>
              <p>{projectName || "先创建一个投标项目，系统会保存全过程中间结果。"}</p>
            </div>
            {busy ? <span className="busy-pill"><i />{busy}</span> : null}
          </div>

          {error ? <div className="message error">{error}</div> : null}
          {notice ? <div className="message success">{notice}</div> : null}

          {step === "project" && (
            <div className="panel-grid two">
              <article className="panel">
                <span className="panel-label">新建项目</span>
                <h3>从一次真实投标开始</h3>
                <label className="field">
                  <span>项目名称</span>
                  <input
                    value={newProjectName}
                    onChange={(event) => setNewProjectName(event.target.value)}
                    placeholder="例如：某市智慧文旅咨询服务项目"
                  />
                </label>
                <button className="primary" onClick={createProject} disabled={Boolean(busy)}>
                  创建项目
                </button>
              </article>

              <article className="panel">
                <span className="panel-label">招标文件</span>
                <h3>上传 PDF 或 DOCX</h3>
                <label className={`upload-zone ${!projectId ? "disabled" : ""}`}>
                  <input
                    type="file"
                    accept=".pdf,.docx"
                    onChange={upload}
                    disabled={!projectId || Boolean(busy)}
                  />
                  <b>选择招标文件</b>
                  <span>PDF 保留页码，DOCX 保留段落位置</span>
                </label>
                <div className="document-list">
                  {documents.length ? documents.map((item) => (
                    <div key={item.id}>
                      <span className={`status-dot ${item.status}`} />
                      <div><strong>{item.filename}</strong><small>{item.status === "parsed" ? `${item.source_count} 个来源片段` : item.error_message}</small></div>
                    </div>
                  )) : <p className="empty">尚未上传文件</p>}
                </div>
                <button className="secondary" onClick={extractRequirements} disabled={!projectId || Boolean(busy)}>
                  提取招标要求
                </button>
              </article>
            </div>
          )}

          {step === "requirements" && (
            <div className="requirement-layout">
              <div className="section-toolbar">
                <div><strong>{requirements.length}</strong><span>条候选要求</span></div>
                <div><strong>{confirmed.length}</strong><span>条已确认</span></div>
                <button className="primary" onClick={() => setStep("writer")} disabled={!confirmed.length}>进入章节生成</button>
              </div>
              <div className="requirement-list">
                {requirements.length ? requirements.map((item) => (
                  <article key={item.id} className={`requirement-card ${item.status}`}>
                    <div className="requirement-top">
                      <span className={`type-tag ${item.type}`}>{typeLabels[item.type]}</span>
                      <span className="confidence">AI 判断 {Math.round(item.confidence * 100)}% · 待人工确认</span>
                    </div>
                    <h3>{item.title}</h3>
                    <div className="response-brief">
                      <span>需要响应什么</span>
                      <p>{item.normalized_text}</p>
                    </div>
                    <div className="evidence-box">
                      <span>招标原文依据</span>
                      <blockquote>{item.quote}</blockquote>
                    </div>
                    <div className="source-row">
                      {item.sources.map((source) => (
                        <span key={source.id} title={source.filename}>{sourceLabel(source)}</span>
                      ))}
                    </div>
                    <div className="card-actions">
                      <button className="ghost danger" onClick={() => setRequirementStatus(item, "rejected")}>排除</button>
                      <button
                        className={item.status === "confirmed" ? "confirmed-button" : "secondary"}
                        onClick={() => setRequirementStatus(item, item.status === "confirmed" ? "pending" : "confirmed")}
                      >
                        {item.status === "confirmed" ? "✓ 已确认" : "确认要求"}
                      </button>
                    </div>
                  </article>
                )) : <div className="empty-state">还没有候选要求，请返回上传文件并执行提取。</div>}
              </div>
            </div>
          )}

          {step === "writer" && (
            <div className="writer-layout">
              <aside className="writer-sidebar panel">
                <span className="panel-label">写作输入</span>
                <label className="field"><span>章节标题</span><input value={sectionTitle} onChange={(event) => setSectionTitle(event.target.value)} /></label>
                <div className="choice-list">
                  {confirmed.map((item) => (
                    <label key={item.id}>
                      <input
                        type="checkbox"
                        checked={selectedRequirementIds.includes(item.id)}
                        onChange={(event) => setSelectedRequirementIds((ids) => event.target.checked ? [...ids, item.id] : ids.filter((id) => id !== item.id))}
                      />
                      <span>{item.title}</span>
                    </label>
                  ))}
                </div>
                <button className="primary" onClick={createAndGenerateSection} disabled={!confirmed.length || Boolean(busy)}>生成一个章节</button>
                {sections.length ? <div className="saved-sections"><small>已保存章节</small>{sections.map((item) => <button key={item.id} className={item.id === activeSectionId ? "active" : ""} onClick={() => { setActiveSectionId(item.id); setEditorContent(item.current_version?.content ?? ""); }}>{item.title}<span>{item.status}</span></button>)}</div> : null}
              </aside>

              <article className="editor-panel">
                <div className="editor-bar">
                  <div><strong>{activeSection?.title ?? "章节编辑器"}</strong><span>{activeSection?.current_version ? `第 ${activeSection.current_version.version_no} 版` : "等待生成"}</span></div>
                  <div><button className="secondary" onClick={saveSection} disabled={!activeSection?.current_version || Boolean(busy)}>保存新版本</button><button className="primary" onClick={approveSection} disabled={!activeSection?.current_version || Boolean(busy)}>人工确认</button></div>
                </div>
                {activeSection?.findings.length ? <div className="findings">{activeSection.findings.map((item) => <p key={item.id} className={item.severity}><b>{item.severity === "blocking" ? "阻断" : "提醒"}</b>{item.message}</p>)}</div> : null}
                <textarea
                  value={editorContent}
                  onChange={(event) => setEditorContent(event.target.value)}
                  placeholder="生成后可在这里人工修改章节内容……"
                  disabled={!activeSection?.current_version}
                />
              </article>
            </div>
          )}

          {step === "export" && (
            <div className="export-layout">
              <article className="delivery-card">
                <span className="delivery-icon">W</span>
                <div><span className="panel-label">WORD DELIVERY</span><h3>{activeSection?.title ?? "技术方案章节"}</h3><p>包含章节正文、要求响应清单以及原文页码/段落来源。</p></div>
                <span className={`approval ${activeSection?.status === "approved" ? "ready" : ""}`}>{activeSection?.status === "approved" ? "已人工确认" : "等待人工确认"}</span>
              </article>
              <article className="panel export-actions">
                <h3>生成交付文件</h3>
                <p>导出前请确认章节中不包含未经核实的案例、资质、参数或承诺。</p>
                <button className="primary large" onClick={createExport} disabled={activeSection?.status !== "approved" || Boolean(busy)}>生成 Word 文件</button>
                {exportItem?.status === "succeeded" ? (
                  <a className="download-button" href={`${API_BASE}/projects/${projectId}/exports/${exportItem.id}/download`}>
                    下载 {exportItem.filename ?? "技术方案.docx"}
                  </a>
                ) : null}
              </article>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
