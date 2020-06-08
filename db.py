import secrets
import sqlite3
from collections import namedtuple


def get_conn():
    return sqlite3.connect("db.sqlite3")


def run_sql(*args):
    conn = get_conn()
    with conn:
        cur = conn.cursor()
        cur.execute(*args)
        lastrowid = cur.lastrowid
        results = cur.fetchall()
    conn.close()
    return results, lastrowid


def init():
    run_sql(
        """
        CREATE TABLE IF NOT EXISTS link (
            slug TEXT UNIQUE,
            drive_id TEXT,
            file_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def create_link(drive_id, file_id):
    """
    Generate 128-byte cryptographically strong slug on the fly to map to a
    (drive_id, file_id) tuple.

    In the very unlikely event of slug collision, retry up to 3 times.
    """
    for i in range(4):
        try:
            _, lastrowid = run_sql(
                "INSERT INTO link (slug, drive_id, file_id) VALUES (?, ?, ?);",
                (secrets.token_urlsafe(128), drive_id, file_id),
            )
            break
        except sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e):
                print("Slug collision - ", end="")
                if i < 3:
                    print(f"Retrying {i+1}...")
                else:
                    print("Gave up.")
                    raise
            else:
                raise

    results, _ = run_sql("SELECT slug FROM link WHERE rowid=?;", (lastrowid,))
    return results[0][0]


Link = namedtuple("Link", ["drive_id", "file_id"])


def get_link(slug):
    results, _ = run_sql("SELECT drive_id, file_id FROM link WHERE slug=?;", (slug,))
    return Link(*results[0]) if results else None


def delete_old_links():
    run_sql(
        """
        DELETE FROM link
        WHERE datetime(created_at) < datetime('now', '-1 day');
        """
    )
