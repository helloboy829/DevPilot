"""评测 CLI：对一次研发任务的产物做 7 字段评分。

用法（在 repo 根目录，PYTHONPATH 含 repo 根 + backend/packages/harness）：

    python -m devpilot.evaluation.cli \
        --requirement "实现一个 JSON 解析器" \
        --workspace /path/to/task/workspace \
        --tests /path/to/test/output.txt \
        --out report.json

输出：一个 JSON 报告文件（7 字段），同时打印到 stdout。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

#: 参与评分的源码文件后缀（按文本处理）。
_SOURCE_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
    ".c", ".h", ".cpp", ".hpp", ".rb", ".php", ".sh", ".md", ".txt",
    ".json", ".yaml", ".yml", ".toml", ".sql",
}

#: 单文件纳入评分的最大字符数（超出则截断，避免 prompt 爆炸）。
_MAX_FILE_CHARS = 4000

#: 纳入评分的文件数上限。
_MAX_FILES = 40


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in _SOURCE_SUFFIXES


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"[读取失败] {exc}"


def collect_artifacts(workspace: Path, *, skip: set[str] | None = None) -> dict[str, str]:
    """扫描 workspace 目录，收集源码/文本文件内容作为评分证据。

    跳过隐藏目录与常见无关目录（.git、__pycache__、node_modules、.venv 等）。
    """
    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", ".pytest_cache", ".mypy_cache", "dist", "build"}
    artifacts: dict[str, str] = {}
    if not workspace.is_dir():
        return artifacts
    for path in sorted(workspace.rglob("*")):
        if len(artifacts) >= _MAX_FILES:
            break
        if not path.is_file() or not _is_text_file(path):
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if skip and path.name in skip:
            continue
        try:
            rel = path.relative_to(workspace).as_posix()
        except ValueError:
            rel = path.name
        content = _read_text(path)
        artifacts[rel] = content[:_MAX_FILE_CHARS] if len(content) > _MAX_FILE_CHARS else content
    return artifacts


async def _run(args: argparse.Namespace) -> int:
    from devpilot.evaluation.runner import judge_with_model

    requirement = args.requirement
    if args.requirement_file:
        requirement = Path(args.requirement_file).read_text(encoding="utf-8", errors="replace")

    artifacts = collect_artifacts(Path(args.workspace)) if args.workspace else {}
    test_summary = _read_text(Path(args.tests)) if args.tests else ""
    transcript_excerpt = _read_text(Path(args.transcript)) if args.transcript else ""

    result = await judge_with_model(
        requirement=requirement,
        artifacts=artifacts,
        test_summary=test_summary,
        transcript_excerpt=transcript_excerpt,
        model_name=args.model,
    )

    report = {
        "evaluation": result.to_dict(),
        "meta": {
            "requirement": requirement[:2000],
            "artifact_count": len(artifacts),
            "artifact_names": list(artifacts.keys()),
            "model": args.model or "(config default)",
        },
    }

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DevPilot 7 字段研发任务评测")
    parser.add_argument("--requirement", help="任务需求文本")
    parser.add_argument("--requirement-file", help="任务需求文本文件")
    parser.add_argument("--workspace", help="产物工作区目录（扫描源码/文本文件）")
    parser.add_argument("--tests", help="测试输出文件（通过/失败信息）")
    parser.add_argument("--transcript", help="研发过程对话摘录（可选，用于幻觉率/置信度）")
    parser.add_argument("--model", default=None, help="评测用模型名（默认取 config.yaml 首个模型）")
    parser.add_argument("--out", help="报告输出 JSON 路径")
    args = parser.parse_args(argv)

    if not args.requirement and not args.requirement_file:
        parser.error("需要 --requirement 或 --requirement-file")
    if not args.workspace:
        parser.error("需要 --workspace 指定产物目录")

    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
