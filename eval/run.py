import argparse
import asyncio
import json
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from eval.config import Settings
from eval.dataset import load_dataset
from eval.metrics import CaseResult, aggregate, hit_at_k, reciprocal_rank
from eval.pipeline_variants import run_search
from eval.setup import build_api_client, ensure_eval_workspace, ensure_fixture_ingested, mint_token

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = REPO_ROOT / "eval" / "datasets" / "sample_pdf_retrieval.jsonl"
REPORTS_DIR = REPO_ROOT / "eval" / "reports"


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the retrieval golden-dataset eval.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("-k", type=int, default=8)
    sparse_group = parser.add_mutually_exclusive_group()
    sparse_group.add_argument("--use-sparse", dest="use_sparse", action="store_true", default=True)
    sparse_group.add_argument("--no-sparse", dest="use_sparse", action="store_false")
    rerank_group = parser.add_mutually_exclusive_group()
    rerank_group.add_argument("--use-rerank", dest="use_rerank", action="store_true", default=True)
    rerank_group.add_argument("--no-rerank", dest="use_rerank", action="store_false")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict:
    settings = Settings()
    cases = load_dataset(args.dataset)

    token = mint_token(settings)
    async with build_api_client() as api_client:
        workspace_id = await ensure_eval_workspace(api_client, token, settings.eval_workspace_name)
        await ensure_fixture_ingested(api_client, token, workspace_id, settings.eval_fixture_path)

    case_results: list[CaseResult] = []
    per_case_detail: list[dict] = []
    for case in cases:
        started = time.monotonic()
        results = run_search(
            uuid.UUID(workspace_id),
            case.question,
            args.k,
            use_sparse=args.use_sparse,
            use_rerank=args.use_rerank,
        )
        latency_ms = (time.monotonic() - started) * 1000

        hit = hit_at_k(case, results)
        case_results.append(
            CaseResult(
                case_id=case.id,
                hit=hit,
                reciprocal_rank=reciprocal_rank(case, results),
                k=args.k,
                latency_ms=latency_ms,
            )
        )
        per_case_detail.append(
            {
                "id": case.id,
                "question": case.question,
                "hit": hit,
                "latency_ms": latency_ms,
                "top_result_pages": [r.page_number for r in results[:3]],
            }
        )

    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{_git_commit()}"
    report = {
        "run_id": run_id,
        "git_commit": _git_commit(),
        "config": {"k": args.k, "use_sparse": args.use_sparse, "use_rerank": args.use_rerank},
        "dataset": str(args.dataset),
        "case_count": len(cases),
        "metrics": aggregate(case_results),
        "cases": per_case_detail,
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"{run_id}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def main() -> None:
    args = _parse_args()
    report = asyncio.run(_run(args))
    print(json.dumps(report["metrics"], indent=2))
    print(f"\nFull report: {report['report_path']}")


if __name__ == "__main__":
    main()
