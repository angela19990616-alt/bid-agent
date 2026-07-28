"use client";

import { ChangeEvent, useMemo, useState } from "react";

type StepId = "materials" | "requirements" | "proposal" | "export";

type Requirement = {
  id: string;
  category: "评分项" | "技术要求" | "交付要求";
  title: string;
  detail: string;
  source: string;
  page: number;
  score?: number;
  confirmed: boolean;
};

type Section = {
  id: string;
  number: string;
  title: string;
  requirementIds: string[];
  status: "ready" | "drafting" | "reviewed";
  words: number;
  score?: number;
};

const steps: Array<{
  id: StepId;
  number: string;
  title: string;
  subtitle: string;
}> = [
  { id: "materials", number: "01", title: "项目材料", subtitle: "上传与解析" },
  { id: "requirements", number: "02", title: "招标要求", subtitle: "提取与确认" },
  { id: "proposal", number: "03", title: "技术方案", subtitle: "目录与章节" },
  { id: "export", number: "04", title: "导出结果", subtitle: "审核与交付" },
];

const initialRequirements: Requirement[] = [
  {
    id: "REQ-001",
    category: "评分项",
    title: "总体服务实施方案",
    detail:
      "针对本项目提供完整的总体服务方案，包括服务目标、工作原则、实施路径及成果体系。",
    source:
      "供应商应结合项目实际情况，制定完整、科学、可执行的总体服务实施方案……",
    page: 38,
    score: 12,
    confirmed: true,
  },
  {
    id: "REQ-002",
    category: "技术要求",
    title: "项目组织与人员配置",
    detail:
      "明确项目负责人、专业团队、职责分工以及内部协同和专家支持机制。",
    source:
      "项目团队应具有完成本项目所需的专业能力，人员配置合理、职责分工清晰……",
    page: 25,
    confirmed: true,
  },
  {
    id: "REQ-003",
    category: "评分项",
    title: "进度计划与节点控制",
    detail:
      "提供分阶段进度计划，明确里程碑、成果交付节点及延期应对措施。",
    source:
      "根据采购人时间要求制定详细工作进度，进度安排合理得 8 分……",
    page: 40,
    score: 8,
    confirmed: false,
  },
  {
    id: "REQ-004",
    category: "交付要求",
    title: "成果质量保障",
    detail:
      "建立三级质量审核机制，说明过程控制、成果复核和问题整改方法。",
    source:
      "所有咨询成果须经过内部质量审核，确保成果内容完整、数据准确……",
    page: 27,
    confirmed: true,
  },
  {
    id: "REQ-005",
    category: "技术要求",
    title: "项目重难点分析",
    detail:
      "结合项目背景识别关键难点，并逐项提出具有针对性的解决措施。",
    source:
      "供应商应充分理解项目特点，对重点、难点进行分析并提出合理化建议……",
    page: 26,
    confirmed: false,
  },
];

const initialSections: Section[] = [
  {
    id: "SEC-01",
    number: "第一章",
    title: "项目理解与总体思路",
    requirementIds: ["REQ-001"],
    status: "reviewed",
    words: 2860,
    score: 91,
  },
  {
    id: "SEC-02",
    number: "第二章",
    title: "项目组织与人员配置",
    requirementIds: ["REQ-002"],
    status: "reviewed",
    words: 2140,
    score: 88,
  },
  {
    id: "SEC-03",
    number: "第三章",
    title: "服务实施方案",
    requirementIds: ["REQ-001", "REQ-003"],
    status: "drafting",
    words: 1680,
  },
  {
    id: "SEC-04",
    number: "第四章",
    title: "项目重难点及解决措施",
    requirementIds: ["REQ-005"],
    status: "ready",
    words: 0,
  },
  {
    id: "SEC-05",
    number: "第五章",
    title: "进度计划与节点控制",
    requirementIds: ["REQ-003"],
    status: "ready",
    words: 0,
  },
  {
    id: "SEC-06",
    number: "第六章",
    title: "质量保障与成果交付",
    requirementIds: ["REQ-004"],
    status: "ready",
    words: 0,
  },
];

const sampleContent = `本项目将坚持“目标牵引、问题导向、协同推进、成果落地”的总体原则，围绕采购人核心诉求建立全过程服务体系。

项目启动后，工作团队首先完成基础材料核验与需求访谈，形成项目任务清单和成果边界；实施阶段按照“资料研究—专题分析—成果编制—内部复核—沟通完善”的路径推进，确保每项工作均有明确责任人、时间节点和验收标准。

针对跨专业协同和成果一致性要求，项目负责人将组织周例会及关键节点专题会，统一技术口径，动态识别进度、质量和沟通风险。所有正式成果执行编制人自校、专业负责人复核、项目负责人审定的三级审核机制。`;

function requirementTag(category: Requirement["category"]) {
  if (category === "评分项") return "score";
  if (category === "交付要求") return "delivery";
  return "technical";
}

export default function Home() {
  const [activeStep, setActiveStep] = useState<StepId>("materials");
  const [requirements, setRequirements] =
    useState<Requirement[]>(initialRequirements);
  const [sections, setSections] = useState<Section[]>(initialSections);
  const [selectedRequirement, setSelectedRequirement] = useState("REQ-001");
  const [selectedSection, setSelectedSection] = useState("SEC-03");
  const [fileName, setFileName] = useState(
    "自贡市智慧文旅新型基础设施建设项目采购文件.docx",
  );
  const [isParsing, setIsParsing] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generatedContent, setGeneratedContent] = useState(sampleContent);
  const [notice, setNotice] = useState("");

  const currentRequirement = requirements.find(
    (item) => item.id === selectedRequirement,
  );
  const currentSection = sections.find((item) => item.id === selectedSection);
  const confirmedCount = requirements.filter((item) => item.confirmed).length;
  const reviewedCount = sections.filter(
    (item) => item.status === "reviewed",
  ).length;
  const totalScore = requirements.reduce(
    (total, item) => total + (item.score ?? 0),
    0,
  );
  const readyToExport = sections.every((item) => item.status === "reviewed");

  const projectProgress = useMemo(() => {
    if (readyToExport) return 100;
    if (reviewedCount > 2) return 76;
    if (reviewedCount > 0) return 58;
    if (confirmedCount === requirements.length) return 42;
    return 28;
  }, [confirmedCount, readyToExport, requirements.length, reviewedCount]);

  function flash(message: string) {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 2600);
  }

  function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    setIsParsing(true);
    window.setTimeout(() => {
      setIsParsing(false);
      flash("文件解析完成，已识别 5 项关键要求");
    }, 1200);
  }

  function toggleRequirement(id: string) {
    setRequirements((items) =>
      items.map((item) =>
        item.id === id ? { ...item, confirmed: !item.confirmed } : item,
      ),
    );
  }

  function confirmAllRequirements() {
    setRequirements((items) =>
      items.map((item) => ({ ...item, confirmed: true })),
    );
    flash("招标要求已全部确认，可以开始规划技术方案");
  }

  function generateSection() {
    if (!currentSection) return;
    setIsGenerating(true);
    setSections((items) =>
      items.map((item) =>
        item.id === currentSection.id
          ? { ...item, status: "drafting" }
          : item,
      ),
    );
    window.setTimeout(() => {
      setGeneratedContent(sampleContent);
      setSections((items) =>
        items.map((item) =>
          item.id === currentSection.id
            ? { ...item, status: "reviewed", words: 2380, score: 90 }
            : item,
        ),
      );
      setIsGenerating(false);
      flash("章节生成并校核完成，综合评分 90 分");
    }, 1500);
  }

  function finishAllSections() {
    setSections((items) =>
      items.map((item, index) => ({
        ...item,
        status: "reviewed",
        words: item.words || 1800 + index * 120,
        score: item.score ?? 86 + (index % 4),
      })),
    );
    flash("演示章节已全部生成并通过校核");
  }

  function downloadDemo() {
    const body = sections
      .map(
        (section) =>
          `${section.number} ${section.title}\n\n${sampleContent}\n\n`,
      )
      .join("");
    const blob = new Blob([`技术方案（演示稿）\n\n${body}`], {
      type: "text/plain;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "技术方案-演示稿.txt";
    anchor.click();
    URL.revokeObjectURL(url);
    flash("演示稿已下载；正式版本将导出为 Word");
  }

  return (
    <main className="app-shell">
      {notice ? <div className="toast">{notice}</div> : null}

      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">岳</span>
          <div>
            <p>DAYUE · BID INTELLIGENCE</p>
            <h1>标书智能工作台</h1>
          </div>
        </div>
        <div className="project-summary">
          <div>
            <span className="summary-label">当前项目</span>
            <strong>自贡市智慧文旅咨询服务项目</strong>
          </div>
          <span className="demo-badge">演示模式</span>
          <button className="avatar" aria-label="用户菜单">
            ZL
          </button>
        </div>
      </header>

      <div className="app-body">
        <aside className="sidebar">
          <div className="progress-card">
            <div className="progress-heading">
              <span>项目进度</span>
              <strong>{projectProgress}%</strong>
            </div>
            <div className="progress-track">
              <i style={{ width: `${projectProgress}%` }} />
            </div>
          </div>

          <nav className="step-nav" aria-label="方案编制步骤">
            {steps.map((step, index) => {
              const activeIndex = steps.findIndex(
                (item) => item.id === activeStep,
              );
              const isComplete = index < activeIndex;
              return (
                <button
                  key={step.id}
                  className={`${activeStep === step.id ? "active" : ""} ${
                    isComplete ? "complete" : ""
                  }`}
                  onClick={() => setActiveStep(step.id)}
                >
                  <span className="step-dot">
                    {isComplete ? "✓" : step.number}
                  </span>
                  <span>
                    <strong>{step.title}</strong>
                    <small>{step.subtitle}</small>
                  </span>
                </button>
              );
            })}
          </nav>

          <div className="sidebar-help">
            <span>?</span>
            <div>
              <strong>使用帮助</strong>
              <p>按四个步骤完成技术方案</p>
            </div>
          </div>
        </aside>

        <section className="content">
          {activeStep === "materials" && (
            <div className="page-enter">
              <div className="page-heading">
                <div>
                  <span className="kicker">STEP 01 · 项目材料</span>
                  <h2>从招标文件开始</h2>
                  <p>上传采购文件，系统将保留原文页码并提取技术要求与评分点。</p>
                </div>
                <button
                  className="primary-button"
                  onClick={() => setActiveStep("requirements")}
                >
                  查看提取结果 <span>→</span>
                </button>
              </div>

              <div className="material-grid">
                <div className="upload-card">
                  <div className="upload-icon">↑</div>
                  <h3>上传招标文件</h3>
                  <p>支持 PDF、DOCX，单个文件不超过 20MB</p>
                  <label className="file-button">
                    选择文件
                    <input
                      type="file"
                      accept=".pdf,.docx"
                      onChange={selectFile}
                    />
                  </label>
                  <small>也可以将文件拖放到此区域</small>
                </div>

                <div className="document-card">
                  <div className="card-title-row">
                    <div>
                      <span className="section-label">已上传材料</span>
                      <h3>项目资料清单</h3>
                    </div>
                    <span className="count-chip">1 份文件</span>
                  </div>
                  <div className="document-row">
                    <span className="file-type">DOC</span>
                    <div className="file-info">
                      <strong>{fileName}</strong>
                      <span>4.8 MB · 2026-07-28 上传</span>
                      <div className="file-meta">
                        <i>{isParsing ? "正在解析" : "解析完成"}</i>
                        <span>86 页</span>
                        <span>312 个段落</span>
                      </div>
                    </div>
                    <button className="more-button" aria-label="文件操作">
                      ···
                    </button>
                  </div>
                  <div className="parse-summary">
                    <div>
                      <span>5</span>
                      <p>关键要求</p>
                    </div>
                    <div>
                      <span>2</span>
                      <p>评分项</p>
                    </div>
                    <div>
                      <span>20</span>
                      <p>相关分值</p>
                    </div>
                    <div>
                      <span>100%</span>
                      <p>页码可追溯</p>
                    </div>
                  </div>
                </div>
              </div>

              <div className="info-strip">
                <span className="info-icon">i</span>
                <div>
                  <strong>当前是可交互的前端演示</strong>
                  <p>
                    页面已内置一份示例招标文件及解析结果。后续接入后端后，上传和解析状态会替换为真实数据。
                  </p>
                </div>
              </div>
            </div>
          )}

          {activeStep === "requirements" && (
            <div className="page-enter">
              <div className="page-heading compact">
                <div>
                  <span className="kicker">STEP 02 · 招标要求</span>
                  <h2>确认系统提取的要求</h2>
                  <p>逐项核对要求及原文依据，确认后用于目录规划和章节审核。</p>
                </div>
                <div className="heading-actions">
                  <span className="confirmed-stat">
                    <strong>{confirmedCount}</strong> / {requirements.length} 已确认
                  </span>
                  <button
                    className="primary-button"
                    onClick={confirmAllRequirements}
                  >
                    全部确认
                  </button>
                </div>
              </div>

              <div className="requirement-layout">
                <div className="requirement-list">
                  <div className="list-toolbar">
                    <span>要求清单</span>
                    <div>
                      <button className="filter-button active">全部</button>
                      <button className="filter-button">评分项</button>
                      <button className="filter-button">待确认</button>
                    </div>
                  </div>
                  {requirements.map((item) => (
                    <button
                      key={item.id}
                      className={`requirement-item ${
                        selectedRequirement === item.id ? "selected" : ""
                      }`}
                      onClick={() => setSelectedRequirement(item.id)}
                    >
                      <span
                        className={`check-box ${
                          item.confirmed ? "checked" : ""
                        }`}
                        onClick={(event) => {
                          event.stopPropagation();
                          toggleRequirement(item.id);
                        }}
                      >
                        {item.confirmed ? "✓" : ""}
                      </span>
                      <span className="requirement-copy">
                        <span className="requirement-meta">
                          <i className={requirementTag(item.category)}>
                            {item.category}
                          </i>
                          <small>{item.id}</small>
                          {item.score ? <b>{item.score} 分</b> : null}
                        </span>
                        <strong>{item.title}</strong>
                        <p>{item.detail}</p>
                      </span>
                      <span className="row-arrow">›</span>
                    </button>
                  ))}
                </div>

                <aside className="source-panel">
                  <div className="source-heading">
                    <div>
                      <span className="section-label">原文依据</span>
                      <h3>{currentRequirement?.title}</h3>
                    </div>
                    <span className="page-chip">
                      第 {currentRequirement?.page} 页
                    </span>
                  </div>
                  <blockquote>“{currentRequirement?.source}”</blockquote>
                  <div className="source-location">
                    <span>采购文件</span>
                    <i>›</i>
                    <span>第五章 采购需求</span>
                    <i>›</i>
                    <strong>技术要求</strong>
                  </div>
                  <button className="secondary-button">在原文件中查看</button>
                  <div className="trace-note">
                    <span>✓</span>
                    <p>该要求已关联原始文件、页码和原文片段，生成章节时将自动保留响应关系。</p>
                  </div>
                </aside>
              </div>

              <div className="bottom-action">
                <div>
                  <strong>确认无遗漏后进入技术方案</strong>
                  <span>未确认项仍可保留，但不会进入自动生成范围。</span>
                </div>
                <button
                  className="primary-button"
                  onClick={() => setActiveStep("proposal")}
                >
                  生成方案目录 <span>→</span>
                </button>
              </div>
            </div>
          )}

          {activeStep === "proposal" && (
            <div className="page-enter proposal-page">
              <div className="page-heading compact">
                <div>
                  <span className="kicker">STEP 03 · 技术方案</span>
                  <h2>按章节生成和审核</h2>
                  <p>每章对应明确的招标要求，生成后自动检查覆盖度与内容质量。</p>
                </div>
                <button className="secondary-button" onClick={finishAllSections}>
                  完成全部章节（演示）
                </button>
              </div>

              <div className="proposal-layout">
                <aside className="outline-panel">
                  <div className="outline-heading">
                    <div>
                      <span className="section-label">方案目录</span>
                      <h3>技术方案</h3>
                    </div>
                    <button aria-label="添加章节">＋</button>
                  </div>
                  <div className="outline-progress">
                    <span>{reviewedCount} / {sections.length} 章已完成</span>
                    <div>
                      <i
                        style={{
                          width: `${(reviewedCount / sections.length) * 100}%`,
                        }}
                      />
                    </div>
                  </div>
                  <div className="section-list">
                    {sections.map((section) => (
                      <button
                        key={section.id}
                        className={
                          selectedSection === section.id ? "selected" : ""
                        }
                        onClick={() => {
                          setSelectedSection(section.id);
                          setGeneratedContent(
                            section.words > 0 ? sampleContent : "",
                          );
                        }}
                      >
                        <span
                          className={`section-state ${section.status}`}
                          aria-label={section.status}
                        >
                          {section.status === "reviewed"
                            ? "✓"
                            : section.status === "drafting"
                              ? "◐"
                              : "·"}
                        </span>
                        <span>
                          <small>{section.number}</small>
                          <strong>{section.title}</strong>
                          <i>
                            {section.words
                              ? `${section.words.toLocaleString()} 字`
                              : "等待生成"}
                          </i>
                        </span>
                        {section.score ? (
                          <b className="section-score">{section.score}</b>
                        ) : null}
                      </button>
                    ))}
                  </div>
                </aside>

                <section className="editor-panel">
                  <div className="editor-heading">
                    <div>
                      <span>
                        {currentSection?.number} · {currentSection?.id}
                      </span>
                      <h3>{currentSection?.title}</h3>
                    </div>
                    <div className="editor-actions">
                      <button className="ghost-button">调整要求</button>
                      <button
                        className="primary-button"
                        onClick={generateSection}
                        disabled={isGenerating}
                      >
                        {isGenerating ? "正在生成…" : "生成本章"}
                      </button>
                    </div>
                  </div>

                  <div className="response-map">
                    <span>本章响应</span>
                    {currentSection?.requirementIds.map((id) => {
                      const requirement = requirements.find(
                        (item) => item.id === id,
                      );
                      return (
                        <button
                          key={id}
                          onClick={() => {
                            setSelectedRequirement(id);
                            setActiveStep("requirements");
                          }}
                        >
                          {id} · {requirement?.title}
                        </button>
                      );
                    })}
                  </div>

                  {isGenerating ? (
                    <div className="generating-state">
                      <div className="generating-orbit">
                        <i />
                      </div>
                      <h3>正在编写“{currentSection?.title}”</h3>
                      <p>检索历史材料 → 组织章节结构 → 生成正文 → 自动校核</p>
                    </div>
                  ) : generatedContent ? (
                    <article className="document-editor">
                      <div className="editor-toolbar">
                        <span>正文预览</span>
                        <div>
                          <button>B</button>
                          <button>H2</button>
                          <button>≡</button>
                          <button>↗</button>
                        </div>
                        <small>{currentSection?.words || 2380} 字</small>
                      </div>
                      <h2>{currentSection?.title}</h2>
                      {generatedContent.split("\n\n").map((paragraph) => (
                        <p key={paragraph}>{paragraph}</p>
                      ))}
                    </article>
                  ) : (
                    <div className="empty-editor">
                      <span>✦</span>
                      <h3>该章节尚未生成</h3>
                      <p>系统将根据关联要求和历史案例逐章编写，不会一次生成整本方案。</p>
                      <button className="primary-button" onClick={generateSection}>
                        开始生成本章
                      </button>
                    </div>
                  )}
                </section>

                <aside className="review-panel">
                  <div className="review-heading">
                    <span className="section-label">自动校核</span>
                    <h3>章节质量</h3>
                  </div>
                  <div className="score-ring">
                    <div>
                      <strong>{currentSection?.score ?? "--"}</strong>
                      <span>综合评分</span>
                    </div>
                  </div>
                  <div className="review-list">
                    <div>
                      <span className="review-status good">✓</span>
                      <p>
                        <strong>要求覆盖</strong>
                        <small>关联要求已完整响应</small>
                      </p>
                    </div>
                    <div>
                      <span className="review-status good">✓</span>
                      <p>
                        <strong>事实检查</strong>
                        <small>未发现虚构案例或参数</small>
                      </p>
                    </div>
                    <div>
                      <span className="review-status warn">!</span>
                      <p>
                        <strong>内容建议</strong>
                        <small>可补充成果交付时间表</small>
                      </p>
                    </div>
                  </div>
                  <button className="secondary-button full">查看审核详情</button>
                </aside>
              </div>

              <div className="bottom-action">
                <div>
                  <strong>章节可随时重写或人工编辑</strong>
                  <span>所有生成结果和审核记录都会保留版本。</span>
                </div>
                <button
                  className="primary-button"
                  onClick={() => setActiveStep("export")}
                >
                  查看导出结果 <span>→</span>
                </button>
              </div>
            </div>
          )}

          {activeStep === "export" && (
            <div className="page-enter export-page">
              <div className="page-heading">
                <div>
                  <span className="kicker">STEP 04 · 导出结果</span>
                  <h2>交付前最后检查</h2>
                  <p>确认章节完整性和审核状态，然后生成可继续编辑的 Word 文档。</p>
                </div>
              </div>

              <div className="export-grid">
                <div className="export-preview">
                  <div className="paper">
                    <span className="paper-brand">大岳咨询</span>
                    <div className="paper-rule" />
                    <p>自贡市智慧文旅新型基础设施建设项目</p>
                    <h3>技术方案</h3>
                    <span className="paper-subtitle">咨询服务采购项目响应文件</span>
                    <div className="paper-seal">岳</div>
                    <small>二〇二六年七月</small>
                  </div>
                </div>

                <div className="export-summary">
                  <span className="section-label">交付检查</span>
                  <h3>技术方案已准备就绪</h3>
                  <p className="export-description">
                    文档共 {sections.length} 个章节，预计 38 页。正式导出将套用公司 Word
                    模板并生成自动目录。
                  </p>

                  <div className="checklist">
                    <div>
                      <span className="check-icon">✓</span>
                      <p>
                        <strong>招标要求</strong>
                        <small>{requirements.length} 项要求已建立原文追溯</small>
                      </p>
                      <b>{confirmedCount}/{requirements.length}</b>
                    </div>
                    <div>
                      <span
                        className={`check-icon ${
                          readyToExport ? "" : "pending"
                        }`}
                      >
                        {readyToExport ? "✓" : "!"}
                      </span>
                      <p>
                        <strong>方案章节</strong>
                        <small>逐章生成并完成自动校核</small>
                      </p>
                      <b>{reviewedCount}/{sections.length}</b>
                    </div>
                    <div>
                      <span className="check-icon">✓</span>
                      <p>
                        <strong>事实安全</strong>
                        <small>未发现无依据的案例、资质和参数</small>
                      </p>
                      <b>通过</b>
                    </div>
                    <div>
                      <span className="check-icon">✓</span>
                      <p>
                        <strong>格式规范</strong>
                        <small>标题层级、页码和自动目录已配置</small>
                      </p>
                      <b>通过</b>
                    </div>
                  </div>

                  <div className="export-options">
                    <label>
                      <input type="checkbox" defaultChecked />
                      包含要求响应索引
                    </label>
                    <label>
                      <input type="checkbox" defaultChecked />
                      包含自动目录和页码
                    </label>
                  </div>

                  <button className="export-button" onClick={downloadDemo}>
                    <span>W</span>
                    下载技术方案演示稿
                  </button>
                  <small className="export-note">
                    当前下载 TXT 演示稿；DOCX 导出接口将在后端阶段接入。
                  </small>
                </div>
              </div>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
