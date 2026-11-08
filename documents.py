import csv
import re
import secrets
import unicodedata
from pathlib import Path

from security import parse_birth_date

ALLOWED={".pdf",".jpg",".jpeg",".png"}


def make_document_filename(title: str, extension: str, documents_dir: Path) -> str:
    """Создаёт безопасное имя файла по названию документа и случайному номеру."""
    extension = (extension or "").lower()
    if extension not in ALLOWED:
        raise ValueError("Разрешены только PDF, JPG и PNG.")

    clean_title = unicodedata.normalize("NFKC", str(title or "Документ"))
    clean_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", clean_title)
    clean_title = re.sub(r"\s+", "_", clean_title)
    clean_title = re.sub(r"_+", "_", clean_title).strip("._ ")
    clean_title = clean_title[:70].rstrip("._ ") or "Документ"

    root = Path(documents_dir)
    root.mkdir(parents=True, exist_ok=True)
    # Проверяем существование, чтобы не перезаписать чужой документ.
    for _ in range(200):
        number = secrets.randbelow(900000) + 100000
        filename = f"{clean_title}_{number}{extension}"
        if not (root / filename).exists():
            return filename
    raise RuntimeError("Не удалось подобрать уникальное имя файла.")

def safe_document_path(value: str, root: Path) -> Path:
    root=Path(root).resolve()
    candidate=(root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Путь к файлу выходит за пределы папки documents.")
    if candidate.suffix.lower() not in ALLOWED:
        raise ValueError("Разрешены только PDF, JPG и PNG.")
    if not candidate.is_file():
        raise ValueError("Файл документа не найден.")
    return candidate

def import_csv(csv_path: Path, db, documents_dir: Path):
    required={"organization","surname","first_name","birth_date","file_path"}
    prepared=[]
    with Path(csv_path).open("r",encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise ValueError("В CSV обязательны столбцы: organization,surname,first_name,birth_date,file_path")
        for line,row in enumerate(reader,2):
            birth=row["birth_date"].strip()
            parsed=parse_birth_date(birth)
            if not parsed: raise ValueError(f"Строка {line}: неверная дата рождения.")
            name=[row["surname"].strip(),row["first_name"].strip(),row.get("patronymic","").strip()]
            if not all(name[:2]): raise ValueError(f"Строка {line}: не заполнены фамилия или имя.")
            if not row["organization"].strip(): raise ValueError(f"Строка {line}: не указана организация.")
            path=safe_document_path(row["file_path"].strip(),documents_dir)
            prepared.append((row["organization"].strip(),name[0],name[1],name[2],parsed,
                row.get("issue_date","").strip(),row.get("title","").strip(),
                row.get("program_context","").strip(),row.get("document_type","").strip(),
                row.get("event_name","").strip(),str(path.relative_to(Path(documents_dir).resolve())),path.name))
    try:
        db.conn.executemany("""INSERT INTO documents(organization,surname,first_name,patronymic,birth_date,
          issue_date,title,program_context,document_type,event_name,file_path,file_name)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",prepared)
        db.conn.commit()
    except Exception:
        db.conn.rollback()
        raise
    return len(prepared)
