import secrets
import sqlite3

# Since we're now running multiprocess instead of multithreaded,
# keeping a global sqlite3 connection per process is fine.
_conn = None


def get_conn():
    global _conn
    return _conn or sqlite3.connect("db.sqlite3")


def run_sql(*args):
    conn = get_conn()
    with conn:
        cur = conn.cursor()
        cur.execute(*args)
        lastrowid = cur.lastrowid
        results = cur.fetchall()
        return results, lastrowid


def run_sqls(*args_list):
    conn = get_conn()
    with conn:
        cur = conn.cursor()
        for args in args_list:
            cur.execute(*args)
        lastrowid = cur.lastrowid
        results = cur.fetchall()
        return results, lastrowid


def init():
    run_sql(
        """
        CREATE TABLE IF NOT EXISTS link (
            slug TEXT UNIQUE,
            file_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    run_sql(
        """
        CREATE TABLE IF NOT EXISTS key_val (
            key TEXT UNIQUE,
            val TEXT
        );
        """
    )


def create_link(file_id):
    """
    Generate 128-byte cryptographically strong slug on the fly to Gdrive file_id.
    In the very unlikely event of slug collision, retry up to 3 times.
    """
    for i in range(4):
        try:
            _, lastrowid = run_sql(
                "INSERT INTO link (slug, file_id) VALUES (?, ?);",
                (secrets.token_urlsafe(128), file_id),
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


def get_or_create_link(file_id):
    results, _ = run_sql("SELECT slug FROM link WHERE file_id=?;", (file_id,))
    if results:
        return results[0][0]
    else:
        return create_link(file_id)


def get_file_id(slug):
    results, _ = run_sql("SELECT file_id FROM link WHERE slug=?;", (slug,))
    return results[0][0] if results else None


def delete_old_links():
    run_sql(
        """
        DELETE FROM link
        WHERE datetime(created_at) < datetime('now', '-1 day');
        """
    )


def keyval_set(key, val):
    # can't use upsert here because sqlite3 on Ubuntu 18 is ancient...
    run_sqls(
        ["DELETE FROM key_val WHERE key=?;", (key,)],
        ["INSERT INTO key_val (key, val) VALUES (?, ?);", (key, val)],
    )


def keyval_get(key, default=""):
    result, _ = run_sql("SELECT val FROM key_val WHERE key=?;", (key,))
    return result[0][0] if result else default
