#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import argparse
import io
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Iterable, Iterator, List, Tuple, Dict, Optional

# -------- Настройки по умолчанию --------

# Расширения, считающиеся текстовыми (добавлены .tsx/.ts/.jsx/.vue и др.)
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

# Игнор по умолчанию
DEFAULT_IGNORES = {
    ".git", ".hg", ".svn",
    ".idea", ".vscode", ".vs",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", "dist", "build", ".next", ".nuxt", ".turbo", ".cache",
    "venv", ".venv", "env", ".tox",
    ".DS_Store", "Thumbs.db",
    ".scannerwork", "coverage", "target", "out",
}

# Файл с дополнительными игнорами (gitignore-стиль, простые маски)
IGNORE_FILE = ".repotoolignore"

# Разделители в Markdown
HR = "\n---\n"

# -------- Утилиты --------

def is_probably_text(path: Path) -> bool:
    """Эвристика для бинарников: проверяем расширение и содержимое."""
    ext = path.suffix.lower()
    if ext in TEXT_EXTS or path.name.lower() in ("makefile", "dockerfile"):
        return True
    try:
        with open(path, "rb") as f:
            sample = f.read(2048)
        # если есть NUL-байты — почти точно бинарь
        if b"\x00" in sample:
            return False
        # допустим небольшой порог «нестандартных» байтов
        nontext = sum(1 for b in sample if b > 0x7F and b < 0xA0)
        return nontext / max(1, len(sample)) < 0.30
    except Exception:
        # если не удалось прочитать — считаем бинарём, чтобы не ломать Markdown
        return False

def read_text_best_effort(path: Path) -> str:
    """Пытаемся прочитать файл в разных кодировках, затем с заменами."""
    encodings = ["utf-8", "utf-16", "cp1251"]
    for enc in encodings:
        try:
            return path.read_text(encoding=enc)
        except Exception:
            pass
    # последняя попытка — «как есть», с заменами
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()

def detect_language_tag(path: Path) -> str:
    """Подбираем язык для подсветки в fenced-блоках по расширению."""
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
    """Поддержка .repotoolignore (простые строки, # комменты, пустые — пропуск)."""
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
    # каталоги и скрытые по умолчанию
    if any(p in default_names for p in parts):
        return True
    if any(p.startswith(".") and p not in (".", "..") for p in parts):
        # скрытые папки/файлы (кроме «.»/«..»)
        return True
    # простые подстрочные/масочные проверки из .repotoolignore
    s = str(rel_path).replace("\\", "/")
    for pat in extra:
        # поддержим несколько простых форматов:
        #  - суффикс "/*" => каталог с любым содержимым
        #  - "*.ext" => маска по расширению
        #  - просто подстрока
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
    """Строим ASCII-дерево относительно root для списка файлов."""
    # Сгруппируем по директориям
    from collections import defaultdict
    dirs: Dict[Path, List[Path]] = defaultdict(list)
    for f in files:
        dirs[f.parent].append(f)

    # Соберём полный набор папок
    all_dirs = set(p.parent for p in files)
    cur = root
    while cur != cur.parent:
        cur = cur.parent  # подстраховка

    def children(d: Path) -> Tuple[List[Path], List[Path]]:
        subdirs = sorted({p for p in all_dirs if p.parent == d}, key=lambda p: p.name.lower())
        leafs = sorted(dirs.get(d, []), key=lambda p: p.name.lower())
        return (subdirs, leafs)

    # Вычислим все иерархии от root
    all_dirs = set()
    for f in files:
        p = f.parent
        while True:
            all_dirs.add(p)
            if p == root:
                break
            p = p.parent

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

# -------- Генерация --------

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
    """Формируем Markdown и, при необходимости, zip с бинарниками."""
    lines: List[str] = []
    lines.append(f"# Project: {root.name}")
    lines.append("")
    lines.append("## Structure")
    lines.append(build_tree(root, files))
    lines.append(HR)

    binaries: List[Path] = []
    for path in files:
        rel = path.relative_to(root)
        if is_probably_text(path):
            lang = detect_language_tag(path)
            header = f"## File: {rel.as_posix()}"
            lines.append(header)
            lines.append("")
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
        # упакуем бинарники в память, ассеты лежат по тем же относительным путям
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for b in binaries:
                zf.write(b, arcname=b.relative_to(root).as_posix())
        zip_bytes = buf.getvalue()

        # запишем раздел с описанием ассетов
        lines.append("## Binary assets")
        lines.append("")
        lines.append("См. рядом лежащий архив `assets.zip` с нетекстовыми файлами проекта.")
        lines.append(HR)

    return "\n".join(lines).rstrip() + "\n", zip_bytes

# -------- Восстановление --------

FILE_SECTION_RE = re.compile(r"^##\s+File:\s+(.+)$", re.MULTILINE)
FENCE_START_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*$")
FENCE_END_RE = re.compile(r"^```\s*$")

def restore_from_markdown(md_text: str, out_dir: Path) -> None:
    """
    Парсим секции вида:

    ## File: path/to/file.ext

    ```lang
    <content>
    ```

    Всё остальное игнорируем (включая блок дерева).
    """
    matches = list(FILE_SECTION_RE.finditer(md_text))
    for idx, m in enumerate(matches):
        rel = Path(m.group(1).strip())
        start = m.end()
        end = matches[idx+1].start() if idx + 1 < len(matches) else len(md_text)
        section = md_text[start:end]

        # найдём первый fenced-блок в секции
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
        # попытка записать в utf-8, если не выйдет — всё равно utf-8 с заменами
        try:
            target_path.write_text(content, encoding="utf-8")
        except Exception:
            with open(target_path, "w", encoding="utf-8", errors="replace") as f:
                f.write(content)

# -------- CLI / интеграция --------

def generate_mode(path: Path, out: Optional[Path], zip_binaries: bool) -> None:
    if not path.is_dir():
        raise SystemExit(f"Ожидалась папка проекта: {path}")
    files = gather_files(path)
    md, zip_bytes = render_markdown(path, files, zip_binaries=zip_binaries)

    if out is None:
        # имя по умолчанию рядом с папкой
        out = Path.cwd() / f"{path.name}_documentation.md"
    out.write_text(md, encoding="utf-8")
    if zip_bytes:
        (out.parent / "assets.zip").write_bytes(zip_bytes)
    print(f"[OK] Документация создана: {out}")

def restore_mode(md_path: Path, out_dir: Optional[Path]) -> None:
    if not md_path.is_file():
        raise SystemExit(f"Ожидался .md файл: {md_path}")
    md = md_path.read_text(encoding="utf-8", errors="ignore")
    base_name = md_path.stem.replace("_documentation", "")
    if out_dir is None:
        out_dir = md_path.parent / base_name
    out_dir.mkdir(parents=True, exist_ok=True)
    restore_from_markdown(md, out_dir)
    # если рядом assets.zip — распакуем
    assets = md_path.parent / "assets.zip"
    if assets.exists():
        with zipfile.ZipFile(assets, "r") as zf:
            zf.extractall(out_dir)
    print(f"[OK] Проект восстановлен в: {out_dir}")

def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="RepoTool",
        description="Генерация Markdown-документации из проекта и восстановление из .md"
    )
    p.add_argument("--mode", choices=["generate","restore"], help="Режим работы")
    p.add_argument("--path", help="Путь: папка проекта (generate) или .md файл (restore)")
    p.add_argument("--out", help="Выход: .md файл (generate) или папка (restore)")
    p.add_argument("--zip-binaries", action="store_true", help="Упаковывать бинарники в assets.zip")
    return p.parse_args(argv)

def main():
    # Если запущено из контекстного меню без аргументов — оставляем старую интерактивную логику.
    args = parse_args(sys.argv[1:])
    if not args.mode or not args.path:
        # Фолбэк: упрощённый диалог через стандартные окна — оставьте как было у вас.
        # Чтобы не тянуть внешние GUI-зависимости, сохраняем CLI-режим «по аргументам».
        print("Использование (CLI):")
        print("  Генерация: RepoTool.exe --mode generate --path <папка> [--out <file.md>] [--zip-binaries]")
        print("  Восстановл: RepoTool.exe --mode restore  --path <file.md> [--out <папка>]")
        return

    base = Path(args.path).resolve()
    out = Path(args.out).resolve() if args.out else None
    if args.mode == "generate":
        generate_mode(base, out, zip_binaries=args.zip_binaries)
    else:
        restore_mode(base, out)

if __name__ == "__main__":
    main()
