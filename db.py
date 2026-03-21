import sqlite3
import os

DB_PATH = "bot.db"
if not os.path.isabs(DB_PATH):
    # 如果是相对路径，确保它是相对于 main.py 所在的目录
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), DB_PATH)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 创建 operators 表 (如果已有可忽略)
    c.execute("""
        CREATE TABLE IF NOT EXISTS operators (
            user_id TEXT PRIMARY KEY,
            name TEXT
        )
    """)

    # 【关键】创建 groups 表，确保包含 last_seen
    c.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            group_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            last_seen INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()
    print(f"✅ 数据库初始化完成: {DB_PATH}")

# --- 操作员相关 (保持不变) ---
def add_operator_db(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO operators(user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def remove_operator_db(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM operators WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def get_operators():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM operators")
    rows = [row[0] for row in c.fetchall()]
    conn.close()
    return rows

# --- 【新增】群组相关操作 ---

def save_group(group_id: str, title: str):
    """
    保存或更新群组信息。
    使用 INSERT OR REPLACE 确保即使存在也会更新 last_seen 和 title。
    """
    import time
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    try:
        c.execute("""
            INSERT OR REPLACE INTO groups (group_id, title, last_seen)
            VALUES (?, ?, ?)
        """, (group_id, title, int(time.time())))

        # 【关键】必须提交事务，否则重启后数据丢失！
        conn.commit()

        # 验证一下是否真的写入了
        c.execute("SELECT count(*) FROM groups")
        count = c.fetchone()[0]
        print(f"💾 [DB] 群组 {title} 已保存。当前数据库总群组数：{count}")

    except Exception as e:
        print(f"❌ [DB Error] 保存群组失败: {e}")
        conn.rollback()
    finally:
        conn.close()

def delete_group_from_db(group_id: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM groups WHERE group_id = ?", (group_id,))
    conn.commit()
    count = c.execute("SELECT count(*) FROM groups").fetchone()[0]
    print(f"🗑️ [DB] 群组 {group_id} 已删除。剩余群组数：{count}")
    conn.close()

def get_all_groups_from_db():
    """返回字典列表：[{'id': ..., 'title': ...}, ...]"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # 让结果可以通过列名访问
    c = conn.cursor()
    c.execute("SELECT group_id, title, last_seen FROM groups")
    rows = c.fetchall()
    conn.close()

    # 转换为字典列表，方便 broadcast.py 使用
    return [{"id": row["group_id"], "title": row["title"], "last_seen": row["last_seen"]} for row in rows]