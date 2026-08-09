from __future__ import annotations

from datetime import datetime
from html import escape

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.services.usage_dashboard_service import UsageDashboardService


router = APIRouter(prefix="/internal", include_in_schema=False)


def get_usage_dashboard_service() -> UsageDashboardService:
    return UsageDashboardService()


def _number(value: object) -> str:
    return f"{int(value or 0):,}"


@router.get("/usage", response_class=HTMLResponse)
def usage_dashboard(
    service: UsageDashboardService = Depends(get_usage_dashboard_service),
):
    data = service.summary()
    totals = data["totals"]
    cards = [
        ("累计方案", _number(totals["projects"])),
        ("处理成功率", f"{totals['job_success_rate']}%"),
        ("已确认章节", _number(totals["approved_sections"])),
        ("Word 导出", _number(totals["exports"])),
        ("模型调用", _number(totals["calls"])),
        ("Token 用量", _number(totals["tokens"])),
    ]
    card_html = "".join(
        f"<article><span>{escape(label)}</span><strong>{escape(value)}</strong></article>"
        for label, value in cards
    )
    model_rows = "".join(
        "<tr>"
        f"<td>{escape(str(row['model']))}</td>"
        f"<td>{escape(str(row['task']))}</td>"
        f"<td>{_number(row['calls'])}</td>"
        f"<td>{_number(row['succeeded'])}</td>"
        f"<td>{_number(row['failed'])}</td>"
        f"<td>{_number(row['tokens'])}</td>"
        f"<td>{escape(str(row['avg_seconds']))}</td>"
        "</tr>"
        for row in data["models"]
    ) or '<tr><td colspan="7">暂无模型调用</td></tr>'
    daily_rows = "".join(
        "<tr>"
        f"<td>{escape(str(row['day']))}</td>"
        f"<td>{_number(row['projects'])}</td>"
        f"<td>{_number(row['jobs_succeeded'])}</td>"
        f"<td>{_number(row['jobs_failed'])}</td>"
        f"<td>{_number(row['exports'])}</td>"
        f"<td>{_number(row['calls'])}</td>"
        f"<td>{_number(row['tokens'])}</td>"
        "</tr>"
        for row in data["daily"]
    )
    job_text = " · ".join(
        f"{escape(str(row['status']))} {_number(row['count'])}"
        for row in data["jobs"]
    ) or "暂无任务"
    updated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    return HTMLResponse(
        "<!doctype html><html lang='zh-CN'><head>"
        "<meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
        "<meta http-equiv='refresh' content='60'>"
        "<title>Bid Agent 使用情况</title><style>"
        "body{font:14px system-ui;background:#f3f5f2;color:#18352c;margin:0;padding:28px}"
        "main{max-width:1100px;margin:auto}h1{margin:0 0 6px}p{color:#60716a}"
        ".cards{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:24px 0}"
        "article{background:white;border:1px solid #d9e1dc;border-radius:12px;padding:18px}"
        "article span{display:block;color:#687b73}article strong{font-size:28px}"
        "section{background:white;border:1px solid #d9e1dc;border-radius:12px;padding:18px;margin:14px 0;overflow:auto}"
        "table{width:100%;border-collapse:collapse}th,td{padding:9px;border-bottom:1px solid #edf0ee;text-align:left;white-space:nowrap}"
        "th{color:#52675e}@media(max-width:720px){.cards{grid-template-columns:1fr 1fr}}"
        "</style></head><body><main>"
        "<h1>Bid Agent 使用情况</h1>"
        f"<p>仅展示聚合数据，不包含文件内容或用户标识。更新时间：{updated}</p>"
        f"<div class='cards'>{card_html}</div>"
        f"<section><h2>任务状态</h2><p>{job_text}</p></section>"
        "<section><h2>近 14 天</h2><table><thead><tr>"
        "<th>日期</th><th>新增方案</th><th>成功任务</th><th>失败任务</th>"
        "<th>导出</th><th>模型调用</th><th>Token</th></tr></thead>"
        f"<tbody>{daily_rows}</tbody></table></section>"
        "<section><h2>模型使用</h2><table><thead><tr>"
        "<th>模型</th><th>任务</th><th>调用</th><th>成功</th><th>失败</th>"
        "<th>Token</th><th>平均秒数</th></tr></thead>"
        f"<tbody>{model_rows}</tbody></table></section>"
        "</main></body></html>"
    )
