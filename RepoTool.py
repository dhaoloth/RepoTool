#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RepoTool — генератор Markdown-документации проекта и восстановитель из .md
Режимы:
- Интерактивный (для Проводника): если передан единственный аргумент `%1` без флагов,
  скрипт определяет режим по типу объекта и открывает стандартные окна выбора путей.
  * Папка -> Генерация -> asksaveasfilename (куда сохранить .md)
  * .md-файл -> Восстановление -> askdirectory (куда восстановить проект)
- CLI (--mode/--path/--out/--zip-binaries): для автоматизации и CI.

Зависимости: только стандартная библиотека Python.
"""

from __future__ import annotations
import argparse
import io
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Iterable, Iterator, List, Tuple, Dict, Optional

# --- GUI для интерактива (стандартные диалоги Windows через tkinter) ---
try:
    # tkinter есть в стандартной поставке CPython для Windows
    import tkinter as tk
    from tkinter import filedialog, messagebox
except Exception:
    tk = None
    filedialog = None
    messagebox = None

# -------- Настройки --------

TEXT_EXTS = {
    ".txt",".md",".rst",".markdown",
    ".py",".pyi",".toml",".ini",".cfg",".conf",".cnf",".yaml",".yml",
    ".json",".jsonc",".csv",".tsv",".log",".gitignore",".gitattributes",
    ".sh",".bash",".zsh",".ps1",".bat",".cmd",".reg",
    ".html",".htm",".xhtml",".xml",
    ".css",".scss",".sass",".less",".styl",
    ".js",".mjs",".cjs",".jsx",
    ".ts",".tsx",
    ".vue",".svelte",
    ".php",".rb",".pl",".pm",
    ".java",".kt",".kts",".groovy",".gradle",".properties",
    ".cs",".fs",".vb",
    ".go",".rs",".c",".h",".cpp",".hpp",".cc",".hh",
    ".swift",".objc",".m",".mm",
    ".sql",".dockerfile",".env",".dotenv",".makefile",".mk",".nuspec",
    ".tex",".bib",
}
DEFAULT_IGNORES = {
    ".git", ".hg", ".svn",
    ".idea", ".vscode", ".vs",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", "dist", "build", ".next", ".nuxt", ".turbo", ".cache",
    "venv", ".venv", "env", ".tox",
    ".DS_Store", "Thumbs.db",
    ".scannerwork", "coverage", "target", "out",
}
IGNORE_FILE = ".repotoolignore"
HR = "\n---\n"

# -------- Утилиты --------

def is_probably_text(path: Path) -> bool:
    ext = path.suffix.lower()
    if ext in TEXT_EXTS or path.name.lower() in ("makefile", "dockerfile"):
        return True
    try:
        with open(path, "rb") as f:
            sample = f.read(2048)
        if b"\x00" in sample:
            return False
        nontext = sum(1 for b in sample if b > 0x7F and b < 0xA0)
        return nontext / max(1, len(sample)) < 0.30
    except Exception:
        return False

def read_text_best_effort(path: Path) -> str:
    encodings = ["utf-8", "utf-16", "cp1251"]
    for enc in encodings:
        try:
            return path.read_text(encoding=enc)
        except Exception:
            pass
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()

def detect_language_tag(path: Path) -> str:
    ext = path.suffix.lower()
    mapping = {
        ".py":"python", ".js":"javascript", ".jsx":"jsx", ".ts":"typescript", ".tsx":"tsx",
        ".json":"json", ".yaml":"yaml", ".yml":"yaml", ".toml":"toml", ".ini":"ini",
        ".md":"markdown", ".html":"html", ".css":"css", ".sh":"bash", ".ps1":"powershell",
        ".bat":"bat", ".cmd":"bat", ".xml":"xml", ".sql":"sql", ".vue":"vue", ".svelte":"svelte",
        ".java":"java", ".kt":"kotlin", ".cs":"csharp", ".go":"go", ".rs":"rust",
        ".c":"c", ".h":"c", ".cpp":"cpp", ".hpp":"cpp",
    }
    return mapping.get(ext, "")

def load_extra_ignores(root: Path) -> List[str]:
    path = root / IGNORE_FILE
    ignores: List[str] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            ignores.append(s)
    return ignores

def should_ignore(rel_path: Path, default_names: set[str], extra: List[str]) -> bool:
    parts = rel_path.parts
    if any(p in default_names for p in parts):
        return True
    if any(p.startswith(".") and p not in (".", "..") for p in parts):
        return True
    s = str(rel_path).replace("\\", "/")
    for pat in extra:
        if pat.endswith("/*"):
            base = pat[:-2]
            if s.startswith(base+"/") or s == base:
                return True
        elif pat.startswith("*."):
            if s.lower().endswith(pat[1:].lower()):
                return True
        else:
            if pat.lower() in s.lower():
                return True
    return False

def build_tree(root: Path, files: List[Path]) -> str:
    from collections import defaultdict
    dirs: Dict[Path, List[Path]] = defaultdict(list)
    for f in files:
        dirs[f.parent].append(f)

    # Собираем множество всех директорий по пути к файлам
    all_dirs = set()
    for f in files:
        p = f.parent
        while True:
            all_dirs.add(p)
            if p == root:
                break
            p = p.parent

    def children(d: Path) -> Tuple[List[Path], List[Path]]:
        subdirs = sorted({p for p in all_dirs if p.parent == d}, key=lambda p: p.name.lower())
        leafs = sorted(dirs.get(d, []), key=lambda p: p.name.lower())
        return (subdirs, leafs)

    def walk(d: Path, prefix: str, lines: List[str]) -> None:
        subdirs, leafs = children(d)
        for i, sd in enumerate(subdirs):
            last = (i == len(subdirs)-1 and not leafs)
            lines.append(f"{prefix}{'└── ' if last else '├── '}{sd.name}/")
            walk(sd, prefix + ("    " if last else "│   "), lines)
        for j, lf in enumerate(leafs):
            is_last = j == len(leafs)-1
            lines.append(f"{prefix}{'└── ' if is_last else '├── '}{lf.name}")

    lines = [f"{root.name}/"]
    walk(root, "", lines)
    return "```text\n" + "\n".join(lines) + "\n```"

def gather_files(root: Path) -> List[Path]:
    extra_ignores = load_extra_ignores(root)
    collected: List[Path] = []
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        rel = p.relative_to(root)
        if should_ignore(rel, DEFAULT_IGNORES, extra_ignores):
            continue
        collected.append(p)
    return collected

def render_markdown(root: Path, files: List[Path], zip_binaries: bool) -> Tuple[str, Optional[bytes]]:
    lines: List[str] = []
    lines.append(f"# Project: {root.name}\n")
    lines.append("## Structure")
    lines.append(build_tree(root, files))
    lines.append(HR)

    binaries: List[Path] = []
    for path in files:
        rel = path.relative_to(root)
        if is_probably_text(path):
            lang = detect_language_tag(path)
            lines.append(f"## File: {rel.as_posix()}\n")
            lines.append(f"```{lang}".rstrip())
            try:
                lines.append(read_text_best_effort(path))
            except Exception as e:
                lines.append(f"<<ERROR READING FILE: {e}>>")
            lines.append("```")
            lines.append(HR)
        else:
            binaries.append(path)

    zip_bytes = None
    if zip_binaries and binaries:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for b in binaries:
                zf.write(b, arcname=b.relative_to(root).as_posix())
        zip_bytes = buf.getvalue()
        lines.append("## Binary assets\n")
        lines.append("См. рядом лежащий архив `assets.zip` с нетекстовыми файлами проекта.")
        lines.append(HR)

    return "\n".join(lines).rstrip() + "\n", zip_bytes

FILE_SECTION_RE = re.compile(r"^##\s+File:\s+(.+)$", re.MULTILINE)
FENCE_START_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*$")
FENCE_END_RE = re.compile(r"^```\s*$")

def restore_from_markdown(md_text: str, out_dir: Path) -> None:
    matches = list(FILE_SECTION_RE.finditer(md_text))
    for idx, m in enumerate(matches):
        rel = Path(m.group(1).strip())
        start = m.end()
        end = matches[idx+1].start() if idx + 1 < len(matches) else len(md_text)
        section = md_text[start:end]

        lines = section.splitlines()
        content_lines: List[str] = []
        in_fence = False
        for ln in lines:
            if not in_fence and FENCE_START_RE.match(ln):
                in_fence = True
                continue
            if in_fence and FENCE_END_RE.match(ln):
                break
            if in_fence:
                content_lines.append(ln)
        content = "\n".join(content_lines)

        target_path = out_dir / rel
        target_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            target_path.write_text(content, encoding="utf-8")
        except Exception:
            with open(target_path, "w", encoding="utf-8", errors="replace") as f:
                f.write(content)

# -------- CLI / интерактив --------

def generate_mode(path: Path, out: Optional[Path], zip_binaries: bool) -> None:
    if not path.is_dir():
        raise SystemExit(f"Ожидалась папка проекта: {path}")
    files = gather_files(path)
    md, zip_bytes = render_markdown(path, files, zip_binaries=zip_binaries)
    if out is None:
        raise SystemExit("Не указан --out в CLI-режиме генерации.")
    out.write_text(md, encoding="utf-8")
    if zip_bytes:
        (out.parent / "assets.zip").write_bytes(zip_bytes)

def restore_mode(md_path: Path, out_dir: Optional[Path]) -> None:
    if not md_path.is_file():
        raise SystemExit(f"Ожидался .md файл: {md_path}")
    md = md_path.read_text(encoding="utf-8", errors="ignore")
    if out_dir is None:
        raise SystemExit("Не указан --out в CLI-режиме восстановления.")
    out_dir.mkdir(parents=True, exist_ok=True)
    restore_from_markdown(md, out_dir)
    assets = md_path.parent / "assets.zip"
    if assets.exists():
        with zipfile.ZipFile(assets, "r") as zf:
            zf.extractall(out_dir)

def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="RepoTool",
        description="Генерация Markdown-документации из проекта и восстановление из .md"
    )
    p.add_argument("--mode", choices=["generate","restore"], help="Режим работы")
    p.add_argument("--path", help="Путь: папка проекта (generate) или .md файл (restore)")
    p.add_argument("--out", help="Выход: .md файл (generate) или папка (restore)")
    p.add_argument("--zip-binaries", action="store_true", help="Упаковывать бинарники в assets.zip (generate)")
    return p.parse_args(argv)

# ---- Интерактивные диалоги (для вызова из Проводника) ----

def run_interactive_with_folder(folder: Path) -> None:
    """Папка -> Генерация; спрашиваем куда сохранить .md и нужен ли assets.zip."""
    if tk is None or filedialog is None:
        raise SystemExit("GUI недоступен (tkinter). Пересоберите Python с Tk.")
    root = tk.Tk()
    root.withdraw()

    # чекбокса в стандартном диалоге нет — спросим через простое окно
    zip_binaries = False
    if messagebox.askyesno(
        "RepoTool — генерация",
        "Упаковать нетекстовые файлы (assets.zip) рядом с .md?\nДа — создать assets.zip\nНет — только .md"
    ):
        zip_binaries = True

    initial_name = f"{folder.name}_documentation.md"
    out_path = filedialog.asksaveasfilename(
        title="Куда сохранить документацию (*.md)",
        defaultextension=".md",
        initialfile=initial_name,
        filetypes=[("Markdown files","*.md"), ("All files","*.*")]
    )
    if not out_path:
        return  # пользователь отменил

    files = gather_files(folder)
    md, zip_bytes = render_markdown(folder, files, zip_binaries=zip_binaries)

    out_file = Path(out_path)
    out_file.write_text(md, encoding="utf-8")
    if zip_binaries and zip_bytes:
        (out_file.parent / "assets.zip").write_bytes(zip_bytes)

    messagebox.showinfo("RepoTool", f"Документация сохранена:\n{out_file}")

def run_interactive_with_md(md_file: Path) -> None:
    """MD-файл -> Восстановление; спрашиваем куда развернуть проект."""
    if tk is None or filedialog is None:
        raise SystemExit("GUI недоступен (tkinter). Пересоберите Python с Tk.")
    root = tk.Tk()
    root.withdraw()

    base_out = filedialog.askdirectory(
        title="Куда восстановить проект (выберите папку)"
    )
    if not base_out:
        return  # пользователь отменил

    md_text = md_file.read_text(encoding="utf-8", errors="ignore")

    # Имя папки проекта возьмём из заголовка или из имени md
    proj_name = md_file.stem.replace("_documentation", "")
    target_dir = Path(base_out) / proj_name
    target_dir.mkdir(parents=True, exist_ok=True)

    restore_from_markdown(md_text, target_dir)

    assets = md_file.parent / "assets.zip"
    if assets.exists():
        with zipfile.ZipFile(assets, "r") as zf:
            zf.extractall(target_dir)

    messagebox.showinfo("RepoTool", f"Проект восстановлен в:\n{target_dir}")

def main():
    args = parse_args(sys.argv[1:])

    # 1) CLI-режим (флаги заданы)
    if args.mode and args.path:
        base = Path(args.path).resolve()
        out = Path(args.out).resolve() if args.out else None
        if args.mode == "generate":
            generate_mode(base, out, zip_binaries=bool(args.zip_binaries))
        else:
            restore_mode(base, out)
        return

    # 2) Режим вызова из Проводника: ожидаем ровно один позиционный аргумент (сам Windows передаёт "%1")
    # PyInstaller --onefile --noconsole передаст argv[1] как путь; parser его не съел (нет позиционных),
    # поэтому просто посмотрим sys.argv вручную.
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(positional) == 1 and not (args.mode or args.path or args.out):
        selected = Path(positional[0]).resolve()
        if selected.is_dir():
            # Папка -> Генерация (с диалогом «Сохранить как»)
            run_interactive_with_folder(selected)
            return
        if selected.is_file() and selected.suffix.lower() == ".md":
            # .md -> Восстановление (с диалогом выбора папки)
            run_interactive_with_md(selected)
            return
        # Если сюда дошли — неизвестный тип объекта
        if messagebox:
            messagebox.showerror("RepoTool", f"Неподдерживаемый тип объекта:\n{selected}")
        return

    # 3) Если вообще нет аргументов — дадим подсказку (в интерактиве окно, иначе stdout)
    help_msg = (
        "RepoTool — использование:\n\n"
        "• В Проводнике:\n"
        "  - ПКМ на папке → «Создать документацию проекта» (откроется диалог «Сохранить как…»)\n"
        "  - ПКМ на .md → «Восстановить проект из документации» (откроется диалог выбора папки)\n\n"
        "• CLI:\n"
        "  RepoTool.exe --mode generate --path <папка> --out <docs.md> [--zip-binaries]\n"
        "  RepoTool.exe --mode restore  --path <docs.md> --out <папка>\n"
    )
    if messagebox:
        root = tk.Tk(); root.withdraw()
        messagebox.showinfo("RepoTool — помощь", help_msg)
    else:
        print(help_msg)

if __name__ == "__main__":
    main()
