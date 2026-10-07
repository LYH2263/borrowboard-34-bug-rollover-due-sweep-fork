from app.db import connect

def init_db():
    c = connect()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS items(
      id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, owner TEXT, status TEXT, data_quality TEXT
    );
    CREATE TABLE IF NOT EXISTS loans(
      id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INT, borrower TEXT, status TEXT,
      due_date TEXT, lent_at TEXT, returned_at TEXT, renewals INT DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    """)
    # 旧库补列：已存在的 loans 表没有 renewals
    cols = {r["name"] for r in c.execute("PRAGMA table_info(loans)")}
    if "renewals" not in cols:
        c.execute("ALTER TABLE loans ADD COLUMN renewals INT DEFAULT 0")
    if c.execute("SELECT COUNT(*) c FROM items").fetchone()["c"] == 0:
        c.executemany("INSERT INTO items(title,owner,status,data_quality) VALUES (?,?,?,?)", [
            ("电钻", "老周", "available", "clean"),
            ("折叠桌", "小陈", "available", "clean"),
            ("脏数据-无主", "", "available", "dirty"),
            ("已外借样例", "阿强", "on_loan", "clean"),
        ])
        c.execute(
            "INSERT INTO loans(item_id,borrower,status,due_date,lent_at) VALUES (?,?,?,?,?)",
            (4, "邻居甲", "active", "2020-06-01", "2020-05-01"),
        )
        c.execute("INSERT INTO settings(key,value) VALUES ('board_name','木色邻里板')")
        # 默认关闭：2020 样例仍算逾期；只有用户在设置页打开开关时才立即补续
        c.execute("INSERT INTO settings(key,value) VALUES ('auto_renew','false')")
        c.commit()
    # 旧库迁移：补上显式默认开关（缺失同样按关闭处理）
    if not c.execute("SELECT 1 FROM settings WHERE key='auto_renew'").fetchone():
        c.execute("INSERT INTO settings(key,value) VALUES ('auto_renew','false')")
        c.commit()
    c.close()
