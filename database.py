import json
import sqlite3
from pathlib import Path
from security import normalize_text

class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          user_id INTEGER PRIMARY KEY, first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          surname TEXT NOT NULL DEFAULT '', first_name TEXT NOT NULL DEFAULT '',
          patronymic TEXT NOT NULL DEFAULT '', birth_date TEXT NOT NULL DEFAULT '',
          profile_updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS sessions(
          user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
          stage TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS documents(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          organization TEXT NOT NULL DEFAULT '',
          surname TEXT NOT NULL, first_name TEXT NOT NULL, patronymic TEXT NOT NULL DEFAULT '',
          event_name TEXT NOT NULL DEFAULT '',
          file_path TEXT NOT NULL, file_name TEXT NOT NULL DEFAULT '',
          enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          issue_date TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '',
          program_context TEXT NOT NULL DEFAULT '', document_type TEXT NOT NULL DEFAULT '',
          birth_date TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS ui_state(
          user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
          screen_message_id TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS organizations(
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, enabled INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS methodists(
          user_id INTEGER PRIMARY KEY, display_name TEXT NOT NULL,
          organization TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          reviewed_at TEXT, reviewed_by INTEGER, rejection_reason TEXT
        );
        """)
        # Мягкая миграция старой базы: данные и документы не удаляются.
        user_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(users)")}
        for name, decl in {
            "surname": "TEXT NOT NULL DEFAULT ''", "first_name": "TEXT NOT NULL DEFAULT ''",
            "patronymic": "TEXT NOT NULL DEFAULT ''", "birth_date": "TEXT NOT NULL DEFAULT ''",
            "profile_updated_at": "TEXT"
        }.items():
            if name not in user_cols:
                self.conn.execute(f"ALTER TABLE users ADD COLUMN {name} {decl}")
        methodist_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(methodists)")}
        for name, decl in {"reviewed_at": "TEXT", "reviewed_by": "INTEGER", "rejection_reason": "TEXT"}.items():
            if name not in methodist_cols:
                self.conn.execute(f"ALTER TABLE methodists ADD COLUMN {name} {decl}")
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(documents)")}
        for name, decl in {
            "issue_date": "TEXT NOT NULL DEFAULT ''", "title": "TEXT NOT NULL DEFAULT ''",
            "program_context": "TEXT NOT NULL DEFAULT ''", "document_type": "TEXT NOT NULL DEFAULT ''",
            "birth_date": "TEXT NOT NULL DEFAULT ''"
        }.items():
            if name not in cols:
                self.conn.execute(f"ALTER TABLE documents ADD COLUMN {name} {decl}")
        self.conn.execute("UPDATE documents SET program_context=event_name WHERE program_context=''")
        self.conn.execute("UPDATE documents SET title=event_name WHERE title=''")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_person_birth ON documents(surname,first_name,patronymic,birth_date)")
        # Наполняем список организаций уже имеющимися данными, чтобы старые записи
        # тоже появлялись в кнопках выбора после миграции.
        self.conn.execute("""INSERT OR IGNORE INTO organizations(name)
          SELECT DISTINCT organization FROM documents
          WHERE TRIM(organization)<>''""")
        self.conn.commit()

    def remember_user(self, uid):
        self.conn.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (uid,)); self.conn.commit()

    def get_profile(self, uid):
        row = self.conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        return dict(row) if row else None

    def save_profile(self, uid, name, birth):
        self.remember_user(uid)
        self.conn.execute("""UPDATE users SET surname=?,first_name=?,patronymic=?,birth_date=?,
          profile_updated_at=CURRENT_TIMESTAMP WHERE user_id=?""", (*name, birth, uid))
        self.conn.commit()

    def set_session(self, uid, stage, payload=None):
        self.remember_user(uid)
        self.conn.execute("""INSERT INTO sessions(user_id,stage,payload) VALUES(?,?,?)
          ON CONFLICT(user_id) DO UPDATE SET stage=excluded.stage,payload=excluded.payload""",
          (uid, stage, json.dumps(payload or {}, ensure_ascii=False)))
        self.conn.commit()

    def get_session(self, uid):
        r = self.conn.execute("SELECT stage,payload FROM sessions WHERE user_id=?", (uid,)).fetchone()
        return (r["stage"], json.loads(r["payload"])) if r else None

    def clear_session(self, uid):
        self.conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,)); self.conn.commit()

    def search_documents(self, profile, query=""):
        """Ищет только документы владельца профиля; query фильтрует метаданные."""
        if not profile or not profile.get("birth_date"):
            return []
        rows = self.conn.execute(
            "SELECT * FROM documents WHERE enabled=1 AND birth_date=? ORDER BY issue_date DESC, id DESC",
            (profile["birth_date"],)
        ).fetchall()
        surname = normalize_text(profile.get("surname", ""))
        first_name = normalize_text(profile.get("first_name", ""))
        patronymic = normalize_text(profile.get("patronymic", ""))
        q = normalize_text(query)
        found = []
        for row in rows:
            d = dict(row)
            if normalize_text(d.get("surname", "")) != surname:
                continue
            if normalize_text(d.get("first_name", "")) != first_name:
                continue
            doc_patronymic = normalize_text(d.get("patronymic", ""))
            # Если отчество указано в профиле, оно должно совпадать.
            # Если не указано, допускаем поиск по ФИ + дате рождения.
            if patronymic and doc_patronymic != patronymic:
                continue
            hay = normalize_text(" ".join(str(d.get(k, "") or "") for k in (
                "title", "document_type", "program_context", "event_name", "organization",
                "issue_date", "file_name"
            )))
            if not q or q in hay:
                found.append(d)
        return found

    def methodist_documents(self, organization, limit=100):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM documents WHERE organization=? AND enabled=1 ORDER BY id DESC LIMIT ?",
            (organization, limit)
        )]

    def get_methodist_document(self, doc_id, organization):
        row = self.conn.execute(
            "SELECT * FROM documents WHERE id=? AND organization=? AND enabled=1",
            (doc_id, organization)
        ).fetchone()
        return dict(row) if row else None

    def update_document(self, doc_id, organization, values):
        allowed = {"surname", "first_name", "patronymic", "birth_date", "title", "program_context",
                   "document_type", "event_name", "issue_date", "file_path", "file_name"}
        values = {k: v for k, v in values.items() if k in allowed}
        if not values:
            return False
        assignments = ", ".join(f"{key}=?" for key in values)
        params = list(values.values()) + [doc_id, organization]
        cur = self.conn.execute(
            f"UPDATE documents SET {assignments} WHERE id=? AND organization=? AND enabled=1", params
        )
        self.conn.commit()
        return cur.rowcount == 1

    def disable_document(self, doc_id, organization):
        cur = self.conn.execute(
            "UPDATE documents SET enabled=0 WHERE id=? AND organization=? AND enabled=1",
            (doc_id, organization)
        )
        self.conn.commit()
        return cur.rowcount == 1

    def get_document(self, doc_id, uid=None):
        row = self.conn.execute("SELECT * FROM documents WHERE id=? AND enabled=1", (doc_id,)).fetchone()
        if not row: return None
        d = dict(row)
        if uid is not None:
            p = self.get_profile(uid)
            if not p:
                return None
            same_base = (normalize_text(d.get("surname", "")) == normalize_text(p.get("surname", "")) and
                         normalize_text(d.get("first_name", "")) == normalize_text(p.get("first_name", "")))
            profile_patronymic = normalize_text(p.get("patronymic", ""))
            same_patronymic = (not profile_patronymic or
                               normalize_text(d.get("patronymic", "")) == profile_patronymic)
            if not same_base or not same_patronymic or d["birth_date"] != p["birth_date"]:
                return None
        return d

    def register_methodist(self, uid, name, org):
        self.conn.execute("""INSERT INTO methodists(user_id,display_name,organization,status)
          VALUES(?,?,?,'pending') ON CONFLICT(user_id) DO UPDATE SET
          display_name=excluded.display_name,organization=excluded.organization,status='pending',
          reviewed_at=NULL,reviewed_by=NULL,rejection_reason=NULL""", (uid,name,org))
        self.conn.commit()

    def get_methodist(self, uid):
        row = self.conn.execute("SELECT * FROM methodists WHERE user_id=?", (uid,)).fetchone()
        return dict(row) if row else None

    def pending_methodists(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM methodists WHERE status='pending' ORDER BY created_at")]

    def review_methodist(self, uid, admin, approved, reason=""):
        cur = self.conn.execute("""UPDATE methodists SET status=?,reviewed_at=CURRENT_TIMESTAMP,
          reviewed_by=?,rejection_reason=? WHERE user_id=? AND status='pending'""",
          ("approved" if approved else "rejected", admin, reason, uid))
        self.conn.commit()
        return cur.rowcount == 1

    def set_screen_message(self, uid, mid):
        self.remember_user(uid)
        self.conn.execute("""INSERT INTO ui_state(user_id,screen_message_id) VALUES(?,?)
          ON CONFLICT(user_id) DO UPDATE SET screen_message_id=excluded.screen_message_id""",(uid,mid))
        self.conn.commit()

    def get_screen_message(self, uid):
        r=self.conn.execute("SELECT screen_message_id FROM ui_state WHERE user_id=?",(uid,)).fetchone()
        return r["screen_message_id"] if r else None

    def add_organization(self, name):
        self.conn.execute("INSERT OR IGNORE INTO organizations(name) VALUES(?)",(name.strip(),))
        self.conn.commit()

    def delete_organization(self, name):
        cur = self.conn.execute("UPDATE organizations SET enabled=0 WHERE name=? AND enabled=1", (name,))
        if cur.rowcount:
            # При отключении организации доступ её методистов также отзывается.
            self.conn.execute("UPDATE methodists SET status='revoked', reviewed_at=CURRENT_TIMESTAMP WHERE organization=? AND status='approved'", (name,))
        self.conn.commit()
        return cur.rowcount == 1

    def organizations(self):
        return [r["name"] for r in self.conn.execute("SELECT name FROM organizations WHERE enabled=1 ORDER BY name")]

    def approved_methodists(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM methodists WHERE status='approved' ORDER BY display_name")]

    def revoke_methodist(self, uid):
        cur = self.conn.execute("UPDATE methodists SET status='revoked', reviewed_at=CURRENT_TIMESTAMP WHERE user_id=? AND status='approved'", (uid,))
        self.conn.commit()
        return cur.rowcount == 1

    def add_document(self, data):
        cur = self.conn.execute("""INSERT INTO documents(organization,surname,first_name,patronymic,birth_date,
          issue_date,title,program_context,document_type,event_name,file_path,file_name)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (
          data['organization'], data['surname'], data['first_name'], data.get('patronymic',''),
          data['birth_date'], data.get('issue_date',''), data['title'], data.get('program_context',''),
          data.get('document_type',''), data.get('event_name',''), data['file_path'], data['file_name']))
        self.conn.commit()
        return cur.lastrowid

    def admin_stats(self):
        def count(table, where=""):
            return self.conn.execute(f"SELECT COUNT(*) FROM {table} {where}").fetchone()[0]
        return {
            "users": count("users"),
            "documents": count("documents", "WHERE enabled=1"),
            "organizations": count("organizations", "WHERE enabled=1"),
            "methodists": count("methodists", "WHERE status='approved'"),
            "pending_methodists": count("methodists", "WHERE status='pending'"),
        }

    def close(self):
        self.conn.close()
