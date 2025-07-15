import os
import sys
import re
import time
import zipfile
from tkinter import messagebox, filedialog, Tk

# --- КОНФИГУРАЦИЯ ---

# Директории, которые нужно полностью игнорировать
IGNORED_DIRS = {'.git', '__pycache__', 'node_modules', '.vscode', '.idea', 'venv', 'env', '.venv', 'dist', 'build'}

# Файлы, которые нужно игнорировать
IGNORED_FILES = {'.gitignore', '.DS_Store', 'Thumbs.db', 'RepoTool.exe', 'RepoTool.py'}

# Расширения файлов, которые считаются текстовыми и включаются в MD-документ
TEXT_EXTENSIONS = {
    '.py', '.js', '.ts', '.html', '.css', '.scss', '.java', '.cpp', '.c', 
    '.h', '.hpp', '.cs', '.php', '.rb', '.go', '.rs', '.swift', '.sql', '.sh', 
    '.bat', '.ps1', '.yaml', '.yml', '.json', '.xml', '.md', '.txt', '.ini', 
    '.toml', '.cfg', '.lock'
}

# Подсказки для подсветки синтаксиса в Markdown
LANGUAGE_MAPPING = {
    '.py': 'python', '.js': 'javascript', '.ts': 'typescript', '.html': 'html', 
    '.css': 'css', '.scss': 'scss', '.java': 'java', '.cpp': 'cpp', '.c': 'c', 
    '.h': 'c', '.hpp': 'cpp', '.cs': 'csharp', '.php': 'php', '.rb': 'ruby',
    '.go': 'go', '.rs': 'rust', '.swift': 'swift', '.sql': 'sql', '.sh': 'bash', 
    '.bat': 'batch', '.ps1': 'powershell', '.yaml': 'yaml', '.yml': 'yaml', 
    '.json': 'json', '.xml': 'xml', '.md': 'markdown', '.txt': 'text', '.ini': 'ini', 
    '.toml': 'toml', '.cfg': 'ini'
}


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ GUI ---

def select_save_file_path(title, initial_dir, initial_file, filetypes):
    """Открывает диалог 'Сохранить как...' и возвращает выбранный путь."""
    root = Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    file_path = filedialog.asksaveasfilename(
        title=title,
        initialdir=initial_dir,
        initialfile=initial_file,
        filetypes=filetypes,
        defaultextension=filetypes[0][1]
    )
    root.destroy()
    return file_path

def select_directory_path(title, initial_dir):
    """Открывает диалог выбора папки и возвращает выбранный путь."""
    root = Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    dir_path = filedialog.askdirectory(title=title, initialdir=initial_dir)
    root.destroy()
    return dir_path


# --- ЛОГИКА ГЕНЕРАЦИИ ДОКУМЕНТАЦИИ ---

def get_project_files(root_path):
    """Рекурсивно сканирует директорию, разделяя файлы на текстовые и бинарные."""
    text_files = []
    binary_files = []
    for dirpath, dirs, files in os.walk(root_path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for filename in files:
            if filename in IGNORED_FILES or filename.endswith(('_documentation.md', '_assets.zip')):
                continue
            
            full_path = os.path.join(dirpath, filename)
            ext = os.path.splitext(filename)[1].lower()
            
            if ext in TEXT_EXTENSIONS:
                text_files.append(full_path)
            else:
                binary_files.append(full_path)
                
    return sorted(text_files), sorted(binary_files)

def read_file_content(path):
    """Читает содержимое текстового файла."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        try:
            with open(path, 'r', encoding='cp1251') as f:
                return f.read()
        except Exception:
            return "[Не удалось прочитать файл в текстовом режиме]"
    except Exception as e:
        return f"[Ошибка чтения файла: {e}]"

def generate_documentation(project_path, output_md_path, archive_warning=""):
    """Создает один MD-файл из исходного кода проекта."""
    project_name = os.path.basename(os.path.normpath(project_path))
    text_files, _ = get_project_files(project_path)
    
    with open(output_md_path, 'w', encoding='utf-8') as f:
        f.write(f"# Документация проекта: {project_name}\n\n")
        f.write(f"**Путь к проекту:** `{project_path}`  \n")
        f.write(f"**Сгенерировано:** {time.strftime('%Y-%m-%d %H:%M:%S')}  \n")
        f.write(f"**Количество текстовых файлов:** {len(text_files)}  \n\n")
        
        if archive_warning:
            f.write(archive_warning)
        
        f.write("## Структура проекта (только текстовые файлы)\n\n```\n")
        for full_path in text_files:
            rel_path = os.path.relpath(full_path, project_path).replace(os.sep, '/')
            f.write(f"{rel_path}\n")
        f.write("```\n\n")
        
        f.write("## Содержимое файлов (для восстановления проекта)\n\n")
        for full_path in text_files:
            rel_path = os.path.relpath(full_path, project_path).replace(os.sep, '/')
            content = read_file_content(full_path)
            lang = LANGUAGE_MAPPING.get(os.path.splitext(rel_path)[1], '')
            
            f.write(f"--- File: {rel_path} ---\n")
            f.write(f"```{lang}\n{content}\n```\n")
            f.write(f"--- End File: {rel_path} ---\n\n---\n\n")


# --- ЛОГИКА ВОССТАНОВЛЕНИЯ ПРОЕКТА ---

START_FILE_PATTERN = re.compile(r"^--- File: (.*) ---$")
END_FILE_PATTERN = re.compile(r"^--- End File: (.*) ---$")
CODE_FENCE_START_PATTERN = re.compile(r"^\s*```(\w*)\s*$")
CODE_FENCE_END_PATTERN = re.compile(r"^\s*```\s*$")

def recreate_project(md_path, output_project_path):
    """Восстанавливает структуру проекта из MD-файла."""
    current_file_path = None
    current_file_lines = []
    files_created = 0

    with open(md_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            start_match = START_FILE_PATTERN.match(line)
            end_match = END_FILE_PATTERN.match(line)

            if start_match:
                current_file_path = start_match.group(1).strip()
                current_file_lines = []
            elif end_match:
                if not current_file_path:
                    continue
                
                if current_file_lines and CODE_FENCE_START_PATTERN.match(current_file_lines[0]):
                    current_file_lines.pop(0)
                if current_file_lines and CODE_FENCE_END_PATTERN.match(current_file_lines[-1]):
                    current_file_lines.pop(-1)

                content_to_write = "\n".join(current_file_lines)
                relative_os_path = os.path.join(*current_file_path.split('/'))
                full_output_path = os.path.join(output_project_path, relative_os_path)
                
                os.makedirs(os.path.dirname(full_output_path), exist_ok=True)
                
                with open(full_output_path, 'w', encoding='utf-8') as outfile:
                    outfile.write(content_to_write)
                
                files_created += 1
                current_file_path = None
                current_file_lines = []
            elif current_file_path is not None:
                current_file_lines.append(line)
    return files_created


################################################################################
###           ДОПОЛНИТЕЛЬНЫЙ ФУНКЦИОНАЛ: РАБОТА С АРХИВАМИ                   ###
###      (Раскомментируйте этот блок, чтобы включить сохранение             ###
###       и восстановление бинарных файлов в .zip архиве)                   ###
################################################################################
#
# def create_asset_archive(project_path, archive_path):
#     """Создает .zip архив с бинарными файлами проекта."""
#     _, binary_files = get_project_files(project_path)
#     if not binary_files:
#         return 0
#     
#     with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
#         for file_path in binary_files:
#             arcname = os.path.relpath(file_path, project_path)
#             zipf.write(file_path, arcname)
#     return len(binary_files)
# 
# def extract_asset_archive(archive_path, output_dir):
#     """Извлекает .zip архив в указанную директорию."""
#     if not os.path.exists(archive_path):
#         print(f"Архив с ресурсами не найден: {archive_path}")
#         return
#     
#     with zipfile.ZipFile(archive_path, 'r') as zipf:
#         zipf.extractall(output_dir)
#     print(f"Ресурсы из архива успешно извлечены в: {output_dir}")
#
################################################################################


# --- ГЛАВНАЯ ФУНКЦИЯ (ТОЧКА ВХОДА) ---

if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            root = Tk()
            root.withdraw()
            messagebox.showerror("Ошибка", "Скрипт должен быть запущен с одним аргументом (путь к файлу или папке).")
            sys.exit(1)

        input_path = sys.argv[1]

        # Определяем режим: ГЕНЕРАЦИЯ
        if os.path.isdir(input_path):
            project_path = os.path.normpath(input_path)
            project_name = os.path.basename(project_path)
            
            initial_dir = os.path.dirname(project_path)
            initial_file = f"{project_name}_documentation.md"
            
            output_md_path = select_save_file_path(
                title="Сохранить файл документации как...",
                initial_dir=initial_dir,
                initial_file=initial_file,
                filetypes=[("Markdown files", "*.md"), ("All files", "*.*")]
            )

            if not output_md_path:
                sys.exit(0)
            
            archive_warning = ""
            # --- Вызов функции архивации (если раскомментировано) ---
            # archive_path = os.path.splitext(output_md_path)[0] + '_assets.zip'
            # try:
            #     if 'create_asset_archive' in globals():
            #         num_archived = create_asset_archive(project_path, archive_path)
            #         if num_archived > 0:
            #             archive_warning = (
            #                 f"> **Внимание:** Для полного восстановления проекта также необходим архив с ресурсами "
            #                 f"`{os.path.basename(archive_path)}`, который был создан рядом с этим файлом.\n\n"
            #             )
            #             print(f"Создан архив с {num_archived} бинарными файлами: {archive_path}")
            # except NameError:
            #     pass # Функция не раскомментирована, ничего не делаем
            
            generate_documentation(project_path, output_md_path, archive_warning)
            messagebox.showinfo("Готово", f"Документация успешно создана!\n\nФайл: {output_md_path}")

        # Определяем режим: ВОССТАНОВЛЕНИЕ
        elif os.path.isfile(input_path) and input_path.endswith('.md'):
            md_path = input_path
            
            initial_dir = os.path.dirname(md_path)
            output_base_dir = select_directory_path(
                title="Выберите папку для восстановления проекта",
                initial_dir=initial_dir
            )

            if not output_base_dir:
                sys.exit(0)

            project_name = os.path.splitext(os.path.basename(md_path))[0].replace('_documentation', '')
            final_project_path = os.path.join(output_base_dir, project_name)

            if os.path.exists(final_project_path):
                messagebox.showerror("Ошибка", f"Папка '{final_project_path}' уже существует.")
                sys.exit(1)
            
            recreate_project(md_path, final_project_path)
            
            # --- Вызов функции извлечения из архива (если раскомментировано) ---
            # archive_path = os.path.splitext(md_path)[0] + '_assets.zip'
            # try:
            #     if 'extract_asset_archive' in globals():
            #         extract_asset_archive(archive_path, final_project_path)
            # except NameError:
            #     pass # Функция не раскомментирована

            messagebox.showinfo("Готово", f"Проект успешно восстановлен!\n\nПапка: {final_project_path}")

        else:
            root = Tk()
            root.withdraw()
            messagebox.showerror("Ошибка", f"Неподдерживаемый тип ввода: {input_path}")

    except Exception as e:
        print(f"Произошла критическая ошибка: {e}")
        root = Tk()
        root.withdraw()
        messagebox.showerror("Критическая ошибка", f"Произошла непредвиденная ошибка:\n\n{e}")
        sys.exit(1)