import hashlib
import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from .search import indexed, match_expression, overlap, project_memory


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def uid() -> str:
    return uuid4().hex


class Conflict(Exception):
    pass


class Missing(Exception):
    pass


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            raise RuntimeError("数据库版本较新，请先更新 yf；未修改数据库。")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS conversations(
              id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS turns(
              id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
              conversation_id TEXT NOT NULL REFERENCES conversations(id),
              status TEXT NOT NULL, recalled_ids TEXT NOT NULL DEFAULT '[]',
              created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages(
              seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
              conversation_id TEXT NOT NULL REFERENCES conversations(id),
              turn_id TEXT NOT NULL REFERENCES turns(id), role TEXT NOT NULL,
              content TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
              UNIQUE(turn_id, role));
            CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id,seq);
            CREATE TABLE IF NOT EXISTS memories(
              id TEXT PRIMARY KEY, outline TEXT NOT NULL, detail TEXT NOT NULL,
              base_importance REAL NOT NULL, importance REAL NOT NULL,
              confidence REAL NOT NULL, reason TEXT NOT NULL,
              tags TEXT NOT NULL, occurred_on TEXT, missing_details TEXT NOT NULL,
              pinned INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'active',
              fingerprint TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memory_sources(
              memory_id TEXT NOT NULL REFERENCES memories(id),
              message_id TEXT NOT NULL REFERENCES messages(id),
              PRIMARY KEY(memory_id,message_id));
            CREATE INDEX IF NOT EXISTS sources_message ON memory_sources(message_id);
            CREATE TABLE IF NOT EXISTS memory_feedback(
              memory_id TEXT PRIMARY KEY REFERENCES memories(id), direction TEXT NOT NULL,
              reason TEXT NOT NULL, source_id TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(
              id TEXT PRIMARY KEY, turn_id TEXT UNIQUE NOT NULL REFERENCES turns(id),
              status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
              available_at TEXT NOT NULL, error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS deletion_records(
              id TEXT PRIMARY KEY, memory_ids TEXT NOT NULL, message_ids TEXT NOT NULL,
              created_at TEXT NOT NULL);
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_search USING fts5(id UNINDEXED, terms);
            CREATE VIRTUAL TABLE IF NOT EXISTS message_search USING fts5(id UNINDEXED, terms);
            PRAGMA user_version=1;
        """)
        with self.lock, self.db:
            defaults = {
                "memory_enabled": True,
                "auto_memory": True,
                "personality": "温和、好奇，真诚交流，允许保留不同看法。",
            }
            for key, value in defaults.items():
                self.db.execute(
                    "INSERT OR IGNORE INTO settings VALUES (?,?)",
                    (key, json.dumps(value, ensure_ascii=False)),
                )
            self.db.execute("UPDATE turns SET status='interrupted' WHERE status='running'")
            self.db.execute("UPDATE messages SET status='interrupted' WHERE status='pending'")
            self.db.execute("UPDATE jobs SET status='pending' WHERE status='running'")

    def close(self):
        with self.lock:
            self.db.close()

    def all(self, sql, params=()):
        with self.lock:
            return [dict(row) for row in self.db.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def settings(self):
        return {row["key"]: json.loads(row["value"]) for row in self.all("SELECT * FROM settings")}

    def update_settings(self, values):
        with self.lock, self.db:
            for key, value in values.items():
                self.db.execute(
                    "UPDATE settings SET value=? WHERE key=?",
                    (json.dumps(value, ensure_ascii=False), key),
                )
        return self.settings()

    def conversation(self, conversation_id):
        row = self.one("SELECT * FROM conversations WHERE id=?", (conversation_id,))
        if not row:
            raise Missing("会话不存在")
        return row

    def create_conversation(self, title):
        record = {"id": uid(), "title": title, "created_at": timestamp(), "updated_at": timestamp()}
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO conversations VALUES (:id,:title,:created_at,:updated_at)", record
            )
        return record

    def conversations(self):
        return self.all("SELECT * FROM conversations ORDER BY updated_at DESC LIMIT 100")

    def messages(self, conversation_id, before=None, limit=80):
        self.conversation(conversation_id)
        rows = self.all(
            "SELECT * FROM messages WHERE conversation_id=? AND seq<? ORDER BY seq DESC LIMIT ?",
            (conversation_id, before or 2**63 - 1, limit),
        )
        return list(reversed(rows))

    def begin_turn(self, conversation_id, request_id, content):
        with self.lock, self.db:
            self.conversation(conversation_id)
            existing = self.one("SELECT * FROM turns WHERE request_id=?", (request_id,))
            if existing:
                user = self.one(
                    "SELECT * FROM messages WHERE turn_id=? AND role='user'", (existing["id"],)
                )
                if existing["conversation_id"] != conversation_id or user["content"] != content:
                    raise Conflict("请求标识已用于不同内容，请刷新后重试。")
                if existing["status"] != "completed":
                    raise Conflict("这条请求正在处理或已经中断；重试请使用新的请求标识。")
                return existing, True
            if self.one(
                "SELECT id FROM turns WHERE conversation_id=? AND status='running'",
                (conversation_id,),
            ):
                raise Conflict("当前会话仍有回答正在生成，请等待或停止后重试。")
            turn_id, now = uid(), timestamp()
            self.db.execute(
                "INSERT INTO turns(id,request_id,conversation_id,status,created_at) VALUES (?,?,?,'running',?)",
                (turn_id, request_id, conversation_id, now),
            )
            for role, text, status in [
                ("user", content, "completed"),
                ("assistant", "", "pending"),
            ]:
                message_id = uid()
                self.db.execute(
                    "INSERT INTO messages(id,conversation_id,turn_id,role,content,status,created_at) VALUES (?,?,?,?,?,?,?)",
                    (message_id, conversation_id, turn_id, role, text, status, now),
                )
                if role == "user":
                    self.db.execute(
                        "INSERT INTO message_search VALUES (?,?)", (message_id, indexed(text))
                    )
            self.db.execute(
                "UPDATE conversations SET updated_at=?,title=CASE WHEN title='新的相处' THEN ? ELSE title END WHERE id=?",
                (now, content[:28], conversation_id),
            )
            return self.one("SELECT * FROM turns WHERE id=?", (turn_id,)), False

    def set_recalled(self, turn_id, ids):
        with self.lock, self.db:
            self.db.execute(
                "UPDATE turns SET recalled_ids=? WHERE id=?", (json.dumps(ids), turn_id)
            )

    def finish_turn(self, turn_id, text, status):
        with self.lock, self.db:
            turn = self.one("SELECT * FROM turns WHERE id=?", (turn_id,))
            if turn["status"] != "running":
                return
            self.db.execute(
                "UPDATE messages SET content=?,status=? WHERE turn_id=? AND role='assistant'",
                (text, status, turn_id),
            )
            self.db.execute("UPDATE turns SET status=? WHERE id=?", (status, turn_id))
            if (
                status == "completed"
                and self.settings()["memory_enabled"]
                and self.settings()["auto_memory"]
            ):
                self.db.execute(
                    "INSERT OR IGNORE INTO jobs(id,turn_id,status,available_at,created_at) VALUES (?,?,'pending',?,?)",
                    (uid(), turn_id, timestamp(), timestamp()),
                )

    def recent_completed(self, conversation_id, limit=24):
        rows = self.all(
            """SELECT m.* FROM messages m JOIN turns t ON t.id=m.turn_id
          WHERE m.conversation_id=? AND t.status='completed' AND m.status='completed'
          ORDER BY m.seq DESC LIMIT ?""",
            (conversation_id, limit),
        )
        return list(reversed(rows))

    @staticmethod
    def decode_memory(row):
        for field in ("tags", "missing_details"):
            row[field] = json.loads(row[field])
        return row

    def raw_memory(self, memory_id):
        row = self.one("SELECT * FROM memories WHERE id=? AND state!='deleted'", (memory_id,))
        if not row:
            raise Missing("记忆不存在或已删除")
        return self.decode_memory(row)

    def memory(self, memory_id, archive=False):
        raw = self.raw_memory(memory_id)
        record = project_memory(raw)
        if archive:
            record["archived_detail"] = raw["detail"]
            record["sources"] = self.all(
                "SELECT m.id,m.content,m.created_at,m.conversation_id FROM messages m JOIN memory_sources s ON s.message_id=m.id WHERE s.memory_id=? ORDER BY m.seq",
                (memory_id,),
            )
        return record

    def memories(self, limit=60, offset=0):
        rows = self.all(
            "SELECT * FROM memories WHERE state!='deleted' ORDER BY pinned DESC,created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [project_memory(self.decode_memory(row)) for row in rows]

    def preference_profile(self):
        rows = self.all(
            "SELECT m.tags,f.direction FROM memory_feedback f JOIN memories m ON m.id=f.memory_id WHERE m.state!='deleted'"
        )
        categories = {}
        for row in rows:
            for tag in json.loads(row["tags"]):
                categories.setdefault(tag, []).append(1 if row["direction"] == "more" else -1)
        return [
            {
                "tag": tag,
                "examples": len(signs),
                "bias": round(sum(signs) / (len(signs) + 3) * 0.2, 3) if len(signs) >= 3 else 0,
            }
            for tag, signs in sorted(categories.items())
        ]

    def add_memory(self, data, source_ids=()):
        data = dict(data)
        tags = list(dict.fromkeys(tag.strip()[:40] for tag in data["tags"] if tag.strip()))
        profile = {row["tag"]: row["bias"] for row in self.preference_profile()}
        bias = sum(profile.get(tag, 0) for tag in tags) / max(1, len(tags))
        importance = max(0, min(1, data["importance"] + bias))
        fingerprint = hashlib.sha256(
            json.dumps(
                [data["outline"], data.get("occurred_on"), sorted(source_ids) or [uid()]],
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        with self.lock, self.db:
            if not self.settings()["memory_enabled"]:
                raise Conflict("记忆保存已暂停")
            for source_id in source_ids:
                source = self.one("SELECT role,status FROM messages WHERE id=?", (source_id,))
                if not source or source["role"] != "user" or source["status"] != "completed":
                    raise Conflict("记忆来源已删除或不可用")
            existing = self.one("SELECT id FROM memories WHERE fingerprint=?", (fingerprint,))
            if existing:
                return self.memory(existing["id"])
            memory_id, now = uid(), timestamp()
            self.db.execute(
                """INSERT INTO memories(id,outline,detail,base_importance,importance,confidence,reason,tags,occurred_on,missing_details,pinned,fingerprint,created_at,updated_at)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    memory_id,
                    data["outline"],
                    data["detail"],
                    importance,
                    importance,
                    data["confidence"],
                    data["reason"],
                    json.dumps(tags, ensure_ascii=False),
                    data.get("occurred_on"),
                    json.dumps(data["missing_details"], ensure_ascii=False),
                    int(data["pinned"]),
                    fingerprint,
                    now,
                    now,
                ),
            )
            self.db.execute(
                "INSERT INTO memory_search VALUES (?,?)",
                (memory_id, indexed(data["outline"] + " " + " ".join(tags))),
            )
            self.db.executemany(
                "INSERT INTO memory_sources VALUES (?,?)",
                [(memory_id, source_id) for source_id in source_ids],
            )
            return self.memory(memory_id)

    def feedback(self, memory_id, direction, reason, source_id=None):
        with self.lock, self.db:
            memory = self.raw_memory(memory_id)
            if source_id:
                source = self.one("SELECT status,role FROM messages WHERE id=?", (source_id,))
                if not source or source["status"] != "completed" or source["role"] != "user":
                    raise Conflict("反馈来源不可用")
            self.db.execute(
                "INSERT INTO memory_feedback VALUES (?,?,?,?,?) ON CONFLICT(memory_id) DO UPDATE SET direction=excluded.direction,reason=excluded.reason,source_id=excluded.source_id,created_at=excluded.created_at",
                (memory_id, direction, reason, source_id, timestamp()),
            )
            importance = max(
                0, min(1, memory["base_importance"] + (0.2 if direction == "more" else -0.2))
            )
            self.db.execute(
                "UPDATE memories SET importance=?,updated_at=? WHERE id=?",
                (importance, timestamp(), memory_id),
            )
            return self.memory(memory_id)

    def pin(self, memory_id, pinned):
        with self.lock, self.db:
            self.raw_memory(memory_id)
            self.db.execute(
                "UPDATE memories SET pinned=?,updated_at=? WHERE id=?",
                (int(pinned), timestamp(), memory_id),
            )
            return self.memory(memory_id)

    def retrieve(self, query, archive=False, limit=6):
        if not self.settings()["memory_enabled"]:
            return []
        expression = match_expression(query)
        if not expression:
            return []
        rows = self.all(
            """SELECT m.* FROM memory_search s JOIN memories m ON m.id=s.id
          WHERE memory_search MATCH ? AND m.state!='deleted'
          ORDER BY bm25(memory_search) LIMIT 60""",
            (expression,),
        )
        scored = []
        for row in rows:
            record = project_memory(self.decode_memory(row))
            relevance = overlap(query, record["outline"] + " " + " ".join(record["tags"]))
            if relevance < 0.14 or (record["detail_level"] == "archived" and not archive):
                continue
            record["relevance"] = round(relevance, 3)
            score = relevance * 0.85 + record["importance"] * 0.1 + record["strength"] * 0.05
            scored.append((score, record))
        return [
            record for _, record in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]
        ]

    def search_archive(self, query, limit=30):
        expression = match_expression(query)
        if not expression:
            return []
        return self.all(
            """SELECT m.id,m.conversation_id,m.content,m.created_at FROM message_search s JOIN messages m ON m.id=s.id
          WHERE message_search MATCH ? AND m.status!='deleted' ORDER BY bm25(message_search) LIMIT ?""",
            (expression, limit),
        )

    def deletion_preview(self, memory_id):
        self.raw_memory(memory_id)
        memory_ids, message_ids, turn_ids = {memory_id}, set(), set()
        # A conservative connected-source closure. The UI previews any collateral records.
        while True:
            before = (len(memory_ids), len(message_ids), len(turn_ids))
            for mid in list(memory_ids):
                message_ids.update(
                    row["message_id"]
                    for row in self.all(
                        "SELECT message_id FROM memory_sources WHERE memory_id=?", (mid,)
                    )
                )
                turn_ids.update(
                    row["id"]
                    for row in self.all(
                        "SELECT t.id FROM turns t WHERE EXISTS (SELECT 1 FROM json_each(t.recalled_ids) j WHERE j.value=?)",
                        (mid,),
                    )
                )
            for sid in list(message_ids):
                row = self.one("SELECT turn_id FROM messages WHERE id=?", (sid,))
                if row:
                    turn_ids.add(row["turn_id"])
            for tid in list(turn_ids):
                message_ids.update(
                    row["id"] for row in self.all("SELECT id FROM messages WHERE turn_id=?", (tid,))
                )
            for sid in list(message_ids):
                memory_ids.update(
                    row["memory_id"]
                    for row in self.all(
                        "SELECT memory_id FROM memory_sources WHERE message_id=?", (sid,)
                    )
                )
            if before == (len(memory_ids), len(message_ids), len(turn_ids)):
                break
        return {
            "memory_ids": sorted(memory_ids),
            "message_ids": sorted(message_ids),
            "turn_ids": sorted(turn_ids),
        }

    def forget(self, memory_id, expected_ids):
        with self.lock, self.db:
            preview = self.deletion_preview(memory_id)
            if sorted(expected_ids) != preview["memory_ids"]:
                raise Conflict("关联记忆发生变化，请重新查看删除范围。")
            for mid in preview["memory_ids"]:
                self.db.execute(
                    "UPDATE memories SET outline='[已删除]',detail='',reason='',tags='[]',missing_details='[]',state='deleted',pinned=0 WHERE id=?",
                    (mid,),
                )
                self.db.execute("DELETE FROM memory_search WHERE id=?", (mid,))
                self.db.execute("DELETE FROM memory_feedback WHERE memory_id=?", (mid,))
            for sid in preview["message_ids"]:
                self.db.execute(
                    "UPDATE messages SET content='[已删除]',status='deleted' WHERE id=?", (sid,)
                )
                self.db.execute("DELETE FROM message_search WHERE id=?", (sid,))
                self.db.execute("DELETE FROM memory_feedback WHERE source_id=?", (sid,))
            for tid in preview["turn_ids"]:
                self.db.execute("UPDATE turns SET status='deleted' WHERE id=?", (tid,))
                self.db.execute(
                    "UPDATE jobs SET status='cancelled',error='' WHERE turn_id=?", (tid,)
                )
                self.db.execute(
                    "UPDATE conversations SET title='已清理的会话' WHERE id=(SELECT conversation_id FROM turns WHERE id=?)",
                    (tid,),
                )
            self.db.execute(
                "INSERT INTO deletion_records VALUES (?,?,?,?)",
                (
                    uid(),
                    json.dumps(preview["memory_ids"]),
                    json.dumps(preview["message_ids"]),
                    timestamp(),
                ),
            )
            return preview

    def claim_job(self):
        with self.lock, self.db:
            settings = self.settings()
            if not settings["memory_enabled"] or not settings["auto_memory"]:
                return None
            row = self.one(
                "SELECT * FROM jobs WHERE status='pending' AND available_at<=? ORDER BY created_at LIMIT 1",
                (timestamp(),),
            )
            if row:
                self.db.execute(
                    "UPDATE jobs SET status='running',attempts=attempts+1 WHERE id=?", (row["id"],)
                )
                row["attempts"] += 1
            return row

    def finish_job(self, job_id, error=None):
        with self.lock, self.db:
            row = self.one("SELECT * FROM jobs WHERE id=?", (job_id,))
            if row["status"] != "running":
                return
            state = "done" if not error else "failed" if row["attempts"] >= 3 else "pending"
            available = (datetime.now(UTC) + timedelta(seconds=30 * row["attempts"])).isoformat()
            self.db.execute(
                "UPDATE jobs SET status=?,error=?,available_at=? WHERE id=?",
                (state, error or "", available, job_id),
            )

    def job_context(self, job):
        turn = self.one("SELECT * FROM turns WHERE id=?", (job["turn_id"],))
        if not turn or turn["status"] != "completed":
            return None
        current = self.one("SELECT * FROM messages WHERE turn_id=? AND role='user'", (turn["id"],))
        rows = self.messages(turn["conversation_id"], before=current["seq"] + 1, limit=7)
        context = [row for row in rows if row["status"] == "completed"]
        previous = self.one(
            "SELECT recalled_ids FROM turns WHERE conversation_id=? AND created_at<? ORDER BY created_at DESC LIMIT 1",
            (turn["conversation_id"], turn["created_at"]),
        )
        known_ids = set(json.loads(turn["recalled_ids"]))
        if previous:
            known_ids.update(json.loads(previous["recalled_ids"]))
        known = []
        for memory_id in list(known_ids)[:12]:
            try:
                known.append(self.memory(memory_id))
            except Missing:
                pass
        return {
            "messages": context,
            "current_source_id": current["id"],
            "known_memories": known,
            "preferences": self.preference_profile(),
        }

    def jobs(self):
        return self.all(
            "SELECT id,status,attempts,error,created_at FROM jobs ORDER BY created_at DESC LIMIT 20"
        )

    def export(self):
        return {
            "format": "yf-archive",
            "version": 1,
            "exported_at": timestamp(),
            "settings": self.settings(),
            "conversations": self.all("SELECT * FROM conversations"),
            "messages": self.all("SELECT * FROM messages ORDER BY seq"),
            "memories": [
                self.decode_memory(row)
                for row in self.all("SELECT * FROM memories WHERE state!='deleted'")
            ],
            "memory_sources": self.all("SELECT * FROM memory_sources"),
            "feedback": self.all("SELECT * FROM memory_feedback"),
            "deletion_records": self.all("SELECT * FROM deletion_records"),
        }

    def backup(self, destination: Path):
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.lock, sqlite3.connect(destination) as target:
            self.db.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("备份一致性检查未通过")
        return destination
