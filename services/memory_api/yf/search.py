"""Small, honest lexical baseline. CJK bigrams are indexed through SQLite FTS5."""

import math
import re
from datetime import UTC, datetime

STOP = set(
    "记得 以前 关于 什么 事情 我们 你们 这个 那个 一个 还是 可以 请问 知道 有没有 现在 今天 昨天 我是 你好 的事 吗呢 how what when where the and you me my is do to a".split()
)


def terms(text: str) -> set[str]:
    result = set(re.findall(r"[a-z0-9_]{2,}", text.lower()))
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        if len(run) == 1:
            result.add(run)
        else:
            result.update(run[i : i + 2] for i in range(len(run) - 1))
    return result - STOP


def indexed(text: str) -> str:
    return " ".join(sorted(terms(text)))


def match_expression(text: str) -> str:
    return " OR ".join('"' + word + '"' for word in sorted(terms(text))[:32])


def overlap(query: str, document: str) -> float:
    left, right = terms(query), terms(document)
    if not left or not right:
        return 0
    return len(left & right) / math.sqrt(len(left) * min(len(right), 40))


def project_memory(row: dict, now: datetime | None = None) -> dict:
    """Age only the working representation; archived source detail remains intact."""
    now = now or datetime.now(UTC)
    age = max(0, (now - datetime.fromisoformat(row["created_at"])).total_seconds() / 86400)
    importance = row["importance"]
    # Starting parameters, deliberately configurable in code until evaluated with actual usage.
    half_life = 3 if importance < 0.3 else 30 if importance < 0.7 else 365
    strength = 1.0 if row["pinned"] else 2 ** (-age / half_life)
    level = "full" if strength >= 0.65 else "fragment" if strength >= 0.25 else "outline"
    if strength < 0.06 and not row["pinned"]:
        level = "archived"
    detail = (
        row["detail"] if level == "full" else row["detail"][:160] if level == "fragment" else ""
    )
    return {key: value for key, value in row.items() if key not in {"detail", "fingerprint"}} | {
        "detail": detail,
        "detail_level": level,
        "strength": round(strength, 4),
        "pinned": bool(row["pinned"]),
    }
