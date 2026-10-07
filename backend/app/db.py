import os, sqlite3
from contextlib import contextmanager
from pathlib import Path

def db_path() -> Path:
    d = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
    d.mkdir(parents=True, exist_ok=True)
    return d / "borrowboard.db"

def connect():
    c = sqlite3.connect(db_path(), timeout=10)
    c.row_factory = sqlite3.Row
    # 零点前后借出 / 归还 / 自动续借三路撞上时，让写锁等待而不是立即报 locked
    c.execute("PRAGMA busy_timeout=10000")
    return c

@contextmanager
def write_tx():
    """持写锁的原子事务：BEGIN IMMEDIATE 先拿 RESERVED 锁，

    事务内的"检查 + 条件更新"对其它写事务整体串行化，提交或异常回滚后释放。
    """
    c = connect()
    try:
        c.execute("BEGIN IMMEDIATE")
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
