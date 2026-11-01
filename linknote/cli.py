"""命令行入口。

    linknote ingest "<链接>" --output ./notes
    linknote doctor
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import load_config
from .errors import LinknoteError
from .log import setup_logging
from .pipeline import ingest
from .store import Store


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="linknote",
        description="把抖音视频 / 微信公众号文章转成有来源、可复核的 Markdown 笔记",
    )
    p.add_argument("--version", action="version", version=f"linknote {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    ing = sub.add_parser("ingest", help="处理一条链接")
    ing.add_argument("url", help="抖音视频链接或公众号文章链接（可整段粘贴分享文案）")
    ing.add_argument("-o", "--output", help="输出目录（默认取 LINKNOTE_OUTPUT 或 ./linknote-notes）")
    ing.add_argument("--force", action="store_true",
                     help="强制重跑：重新获取内容、重新转写、重新摘要（旧笔记备份为 .bak）")
    ing.add_argument("--extract-only", action="store_true",
                     help="只提取元信息与原生正文，不下载视频、不调模型；与 --keep-media 同时给出时以此为准")
    ing.add_argument("--keep-media", dest="keep_media", action="store_true", default=None,
                     help="长期保留原视频（默认不保留，抽完音轨即删）")
    ing.add_argument("--no-keep-media", dest="keep_media", action="store_false",
                     help="不保留原视频（覆盖配置）")
    ing.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    ing.add_argument("--dialect", choices=["plain", "obsidian"], default=None,
                     help="Markdown 风格：plain（默认，任何编辑器）或 obsidian（用 callout）")
    ing.add_argument("--no-frontmatter", action="store_true",
                     help="不写 YAML frontmatter（Notion/Word 导入更省心）")
    ing.add_argument("-v", "--verbose", action="store_true", help="打印调试日志")
    ing.add_argument("--env-file", help="指定 .env 文件路径")

    sub.add_parser("doctor", help="检查依赖与配置（密钥脱敏显示）")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "doctor":
        return _doctor(args)

    cfg = load_config(args.env_file)
    if args.output:
        cfg.output_dir = Path(args.output).expanduser()
    if args.dialect:
        cfg.dialect = args.dialect
    if args.no_frontmatter:
        cfg.frontmatter = False

    store = Store(cfg.output_dir)
    try:
        store.prepare()
    except LinknoteError as exc:
        print(f"✗ {exc.message}" + (f"\n  提示：{exc.hint}" if exc.hint else ""), file=sys.stderr)
        return 2

    logger = setup_logging(store.state_dir / "runs", verbose=args.verbose)

    try:
        result = ingest(args.url, cfg, force=args.force,
                        extract_only=args.extract_only,
                        keep_media=args.keep_media, logger=logger)
    except LinknoteError as exc:
        payload = {"status": "failed", "stage": exc.stage, "code": exc.code,
                   "message": exc.message, "hint": exc.hint}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(f"✗ [{exc.code}] {exc.message}", file=sys.stderr)
            if exc.hint:
                print(f"  提示：{exc.hint}", file=sys.stderr)
        return 2
    except Exception as exc:                      # 兜底：不让用户看到裸堆栈
        if args.verbose:
            logger.exception("未预期错误")
        msg = f"未预期错误：{type(exc).__name__}: {exc}"
        if args.json:
            print(json.dumps({"status": "failed", "code": "unexpected",
                              "message": msg}, ensure_ascii=False))
        else:
            print(f"✗ {msg}", file=sys.stderr)
            print("  提示：加 -v 重跑可以看到完整堆栈；这属于工具 bug，欢迎带日志提 issue",
                  file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False))
    else:
        icon = {"complete": "✓", "partial": "!", "failed": "✗", "skipped": "·"}[result.status]
        print(f"{icon} {result.status}｜{result.title or '(无标题)'}")
        print(f"  笔记：{result.note_path}")
        if result.message:
            print(f"  说明：{result.message}")
        for w in result.warnings:
            print(f"  - {w}")
    return 0 if result.status in ("complete", "partial", "skipped") else 1


def _doctor(args) -> int:
    cfg = load_config(getattr(args, "env_file", None))
    info = cfg.redacted()
    print(f"linknote {__version__}")
    print(json.dumps(info, ensure_ascii=False, indent=2))

    ok = True
    try:
        import requests  # noqa: F401
        print("· requests：已安装")
    except ImportError:
        print("✗ requests：缺失（pip install requests）")
        ok = False

    try:
        import playwright  # noqa: F401
        print("· playwright：已安装（抖音适配器可用）")
    except ImportError:
        print("! playwright：未安装 → 抖音链接无法处理（pip install 'linknote[douyin]'）")

    import shutil as _sh
    print("· ffmpeg：" + ("已安装" if _sh.which("ffmpeg") else "未安装 → 无法转写音频"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
