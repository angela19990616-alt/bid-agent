from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.knowledge.permissions import KnowledgeAccessContext
from app.memory.case_pair_batch import (
    CasePairBatchImporter,
    CasePairManifestError,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="批量验证并导入机构私有招标文件与中标响应案例。"
    )
    parser.add_argument("manifest", type=Path, help="案例清单 JSON")
    parser.add_argument(
        "--expected-pairs",
        type=int,
        default=5,
        help="要求的完整案例组数，默认 5",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只验证文件和结构隔离，不写数据库",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.expected_pairs < 1 or args.expected_pairs > 100:
        raise SystemExit("expected-pairs 必须在 1 到 100 之间。")
    try:
        report = CasePairBatchImporter().run(
            args.manifest,
            access_context=KnowledgeAccessContext.default(),
            expected_pairs=args.expected_pairs,
            dry_run=args.dry_run,
        )
    except CasePairManifestError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(report.snapshot(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
