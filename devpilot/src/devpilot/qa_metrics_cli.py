"""离线技术指标投影 CLI：只读取本地 JSON，零网络、零模型调用。

输出固定 schema 的 TTFT/吞吐、裁判校准或图像差异投影。缺失/不可观测值保持
``null``，绝不填零；任何结果都不代表质量 PASS、证据或批准。
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

from .qa_cv_metrics import compute_image_diff
from .qa_judge_calibration import compute_judge_calibration
from .qa_stream_metrics import compute_stream_metrics

_ERROR = "Invalid metric input"
_MAX_FILE_BYTES = 1_048_576


def _read_json(path):
    source = Path(path)
    original = source.lstat()
    if (
        not stat.S_ISREG(original.st_mode)
        or not 1 <= original.st_size <= _MAX_FILE_BYTES
    ):
        raise ValueError(_ERROR)
    descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        current = os.fstat(descriptor)
        if (current.st_dev, current.st_ino) != (
            original.st_dev,
            original.st_ino,
        ) or not stat.S_ISREG(current.st_mode):
            raise ValueError(_ERROR)
        data = os.read(descriptor, _MAX_FILE_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(data) != original.st_size or len(data) > _MAX_FILE_BYTES:
        raise ValueError(_ERROR)
    return json.loads(data.decode("utf-8"))


def main(argv=None):
    """Run one explicit offline projection; never sends or approves."""

    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise ValueError(_ERROR)

    parser = Parser(
        description="Offline technical metric projections over explicit local JSON. No network, model calls or approval.",
        allow_abbrev=False,
    )
    operations = parser.add_subparsers(dest="operation", required=True)
    stream = operations.add_parser("stream", allow_abbrev=False)
    stream.add_argument("--observation", required=True)
    calibration = operations.add_parser("calibration", allow_abbrev=False)
    calibration.add_argument("--pairs", required=True)
    image = operations.add_parser("image-diff", allow_abbrev=False)
    image.add_argument("--reference", required=True)
    image.add_argument("--candidate", required=True)
    image.add_argument("--threshold", type=int, default=0)
    try:
        args = parser.parse_args(argv)
        if args.operation == "stream":
            result = compute_stream_metrics(_read_json(args.observation))
        elif args.operation == "calibration":
            result = compute_judge_calibration(_read_json(args.pairs))
        else:
            result = compute_image_diff(
                _read_json(args.reference),
                _read_json(args.candidate),
                threshold=args.threshold,
            )
        print(json.dumps(result, sort_keys=True, ensure_ascii=True, allow_nan=False))
        return 0
    except KeyboardInterrupt:
        print(_ERROR, file=sys.stderr)
        return 130
    except Exception:
        print(_ERROR, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
