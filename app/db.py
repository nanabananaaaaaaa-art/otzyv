import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Manager:
    telegram_id: int
    name: str
    city: str


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                create table if not exists managers (
                    telegram_id integer primary key,
                    name text not null,
                    city text not null,
                    created_at text not null
                );

                create table if not exists reviews (
                    id integer primary key autoincrement,
                    manager_id integer not null references managers(telegram_id),
                    platform text not null,
                    client_name text not null,
                    review_text text not null,
                    attachment_file_id text,
                    status text not null default 'pending',
                    price integer not null,
                    created_at text not null,
                    checked_at text
                );
                """
            )

    def upsert_manager(self, telegram_id: int, name: str, city: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                insert into managers (telegram_id, name, city, created_at)
                values (?, ?, ?, ?)
                on conflict(telegram_id) do update set
                    name = excluded.name,
                    city = excluded.city
                """,
                (telegram_id, name, city, now),
            )

    def get_manager(self, telegram_id: int) -> Manager | None:
        with self.connect() as conn:
            row = conn.execute(
                "select telegram_id, name, city from managers where telegram_id = ?",
                (telegram_id,),
            ).fetchone()
        if not row:
            return None
        return Manager(row["telegram_id"], row["name"], row["city"])

    def add_review(
        self,
        manager_id: int,
        platform: str,
        client_name: str,
        review_text: str,
        attachment_file_id: str | None,
        price: int,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            cur = conn.execute(
                """
                insert into reviews
                    (manager_id, platform, client_name, review_text, attachment_file_id, price, created_at)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (manager_id, platform, client_name, review_text, attachment_file_id, price, now),
            )
            return int(cur.lastrowid)

    def set_review_status(self, review_id: int, status: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            cur = conn.execute(
                """
                update reviews
                set status = ?, checked_at = ?
                where id = ?
                """,
                (status, now, review_id),
            )
            return cur.rowcount > 0

    def get_stats(self, manager_id: int | None = None) -> list[sqlite3.Row]:
        where = ""
        params: tuple[int, ...] = ()
        if manager_id is not None:
            where = "where m.telegram_id = ?"
            params = (manager_id,)

        with self.connect() as conn:
            return conn.execute(
                f"""
                select
                    m.telegram_id,
                    m.name,
                    m.city,
                    count(r.id) as total_reviews,
                    sum(case when r.status = 'pending' then 1 else 0 end) as pending_reviews,
                    sum(case when r.status = 'approved' then 1 else 0 end) as approved_reviews,
                    coalesce(sum(case when r.status = 'approved' then r.price else 0 end), 0) as earned
                from managers m
                left join reviews r on r.manager_id = m.telegram_id
                {where}
                group by m.telegram_id, m.name, m.city
                order by earned desc, approved_reviews desc
                """,
                params,
            ).fetchall()

    def list_pending_reviews(self, limit: int = 10) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                select r.*, m.name, m.city
                from reviews r
                join managers m on m.telegram_id = r.manager_id
                where r.status = 'pending'
                order by r.created_at asc
                limit ?
                """,
                (limit,),
            ).fetchall()
