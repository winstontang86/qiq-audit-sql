#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qiq-audit-sql skill 构建脚本

功能：
1. 从 SKILL.md 的 front matter 读取 version 字段作为版本号
2. 清空 dist/ 目录下旧的 zip 包，保证只保留最新版本
3. 将 skill 必要文件打包到 dist/qiq-audit-sql-<version>.zip

打包内容（必要文件）：
- SKILL.md
- LICENSE
- scripts/        （排除 __pycache__、build.py 自身、*.pyc）
- references/
- examples/

仅依赖 Python 3 标准库。

用法：
    python3 scripts/build.py            # 使用 SKILL.md 中的 version
    python3 scripts/build.py -v 0.2.0   # 显式指定版本号（同时回写到 SKILL.md）
    python3 scripts/build.py -o out/    # 指定输出目录（默认 dist/）
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Iterable

SKILL_NAME = "qiq-audit-sql"

# 仓库根目录（脚本位于 <root>/scripts/build.py）
ROOT = Path(__file__).resolve().parent.parent

# 需要打包进 zip 的条目，相对于仓库根目录
INCLUDE_PATHS: list[str] = [
    "SKILL.md",
    "LICENSE",
    "scripts",
    "references",
    "examples",
]

# 打包时需要排除的文件/目录名（按 basename 匹配）
EXCLUDE_NAMES: set[str] = {
    "__pycache__",
    ".DS_Store",
    ".git",
    ".gitignore",
    "build.py",  # 构建脚本自身不打包
}

# 排除的文件后缀
EXCLUDE_SUFFIXES: set[str] = {".pyc", ".pyo", ".zip"}


# ---------- 版本号读写 ----------

_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_VERSION_LINE_RE = re.compile(r"^version\s*:\s*(.+?)\s*$", re.MULTILINE)


def read_version(skill_md: Path) -> str:
    text = skill_md.read_text(encoding="utf-8")
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        sys.exit(f"[build] 错误：{skill_md} 缺少 front matter")
    fm = m.group(1)
    vm = _VERSION_LINE_RE.search(fm)
    if not vm:
        sys.exit(f"[build] 错误：{skill_md} front matter 中未找到 version 字段")
    return vm.group(1).strip().strip('"').strip("'")


def write_version(skill_md: Path, version: str) -> None:
    text = skill_md.read_text(encoding="utf-8")
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        sys.exit(f"[build] 错误：{skill_md} 缺少 front matter")
    fm = m.group(1)
    if _VERSION_LINE_RE.search(fm):
        new_fm = _VERSION_LINE_RE.sub(f"version: {version}", fm, count=1)
    else:
        # 追加到 name 后面，保持可读性
        if re.search(r"^name\s*:", fm, re.MULTILINE):
            new_fm = re.sub(
                r"^(name\s*:.*)$",
                r"\1\nversion: " + version,
                fm,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            new_fm = fm + f"\nversion: {version}"
    new_text = text[: m.start(1)] + new_fm + text[m.end(1):]
    skill_md.write_text(new_text, encoding="utf-8")


# ---------- 打包逻辑 ----------

def _should_skip(path: Path) -> bool:
    if path.name in EXCLUDE_NAMES:
        return True
    if path.suffix in EXCLUDE_SUFFIXES:
        return True
    return False


def iter_files(root: Path, includes: Iterable[str]) -> Iterable[Path]:
    for rel in includes:
        p = root / rel
        if not p.exists():
            print(f"[build] 警告：跳过不存在的路径 {rel}", file=sys.stderr)
            continue
        if p.is_file():
            if not _should_skip(p):
                yield p
            continue
        # 目录：递归遍历，沿途裁剪被排除的目录
        for dirpath, dirnames, filenames in os.walk(p):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_NAMES]
            for fn in filenames:
                fp = Path(dirpath) / fn
                if not _should_skip(fp):
                    yield fp


def clean_old_zips(dist_dir: Path) -> int:
    if not dist_dir.exists():
        return 0
    n = 0
    for old in dist_dir.glob(f"{SKILL_NAME}-*.zip"):
        try:
            old.unlink()
            n += 1
            print(f"[build] 已删除旧包：{old.name}")
        except OSError as e:
            print(f"[build] 警告：删除 {old} 失败: {e}", file=sys.stderr)
    return n


def build_zip(version: str, dist_dir: Path) -> Path:
    dist_dir.mkdir(parents=True, exist_ok=True)
    clean_old_zips(dist_dir)

    zip_path = dist_dir / f"{SKILL_NAME}-{version}.zip"
    # zip 内顶层目录名，便于解压后直接得到 skill 根
    top = f"{SKILL_NAME}-{version}"

    files = sorted(iter_files(ROOT, INCLUDE_PATHS))
    if not files:
        sys.exit("[build] 错误：没有任何文件可打包")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in files:
            arc = Path(top) / fp.relative_to(ROOT)
            zf.write(fp, arcname=str(arc))

    size_kb = zip_path.stat().st_size / 1024.0
    print(f"[build] 打包完成：{zip_path}  ({len(files)} 个文件, {size_kb:.1f} KB)")
    return zip_path


# ---------- CLI ----------

def main() -> int:
    parser = argparse.ArgumentParser(description=f"Build {SKILL_NAME} skill zip")
    parser.add_argument(
        "-v", "--version",
        help="指定版本号（同时回写 SKILL.md），不传则使用 SKILL.md 中的 version",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=str(ROOT / "dist"),
        help="输出目录（默认 dist/）",
    )
    args = parser.parse_args()

    skill_md = ROOT / "SKILL.md"
    if not skill_md.exists():
        sys.exit(f"[build] 错误：未找到 {skill_md}")

    if args.version:
        version = args.version.strip()
        write_version(skill_md, version)
        print(f"[build] 已写入版本号到 SKILL.md: {version}")
    else:
        version = read_version(skill_md)
        print(f"[build] 当前版本号：{version}")

    dist_dir = Path(args.output_dir).resolve()
    build_zip(version, dist_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
