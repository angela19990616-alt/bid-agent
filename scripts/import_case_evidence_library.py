from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.knowledge.engine import EnterpriseKnowledgeEngine
from app.database.db import connect


def main() -> int:
    parser = argparse.ArgumentParser(
        description="导入五份机构私有中标响应文件，用于严格回填候选值及依据展示。"
    )
    parser.add_argument(
        "manifest",
        type=Path,
        nargs="?",
        default=ROOT / "database/case-pairs.local.json",
    )
    args = parser.parse_args()
    manifest = args.manifest.resolve()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    pairs = payload.get("pairs", [])
    if len(pairs) != 5:
        raise SystemExit("案例证据库必须包含 5 组完整案例。")
    engine = EnterpriseKnowledgeEngine()
    results = []
    for index, pair in enumerate(pairs, start=1):
        path = (manifest.parent / pair["winning_proposal"]).resolve()
        if manifest.parent not in path.parents or not path.is_file():
            raise SystemExit(f"第 {index} 组中标响应文件不存在。")
        result = engine.import_document(
            path.name,
            path.read_bytes(),
            source_role="historical_case_proposal",
            # The private winning bids contain many scanned certificate images.
            # This trusted local-only importer extracts text and never exposes
            # the binary file through the knowledge API.
            max_size_bytes=512 * 1024 * 1024,
        )
        evidence_title = f"案例{index}·{pair.get('project_type') or path.parent.name}·中标响应文件"
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE enterprise_knowledge
                    SET title = %s,
                        metadata = metadata || %s::jsonb,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        evidence_title,
                        json.dumps({
                            "case_index": index,
                            "project_type": pair.get("project_type"),
                            "industry": pair.get("industry"),
                        }, ensure_ascii=False),
                        result["id"],
                    ),
                )
        results.append({
            "case": index,
            "status": result["import_status"],
            "title": evidence_title,
            "text_chars": result["text_chars"],
        })
    print(json.dumps({"count": len(results), "items": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
