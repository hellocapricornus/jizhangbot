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

    # 【关键】创建 groups 表，确保包含 last_seen 和 category
    c.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            group_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            last_seen INTEGER DEFAULT 0,
            category TEXT DEFAULT '未分类'
        )
    """)

    # 新增：分类管理表
    c.execute("""
        CREATE TABLE IF NOT EXISTS group_categories (
            category_id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_name TEXT UNIQUE NOT NULL,
            created_at INTEGER DEFAULT 0,
            description TEXT
        )
    """)

    # 初始化默认分类
    default_categories = ['未分类', 'VIP群组', '普通群组', '测试群组', '代理群组']
    import time
    now = int(time.time())
    for cat in default_categories:
        c.execute("INSERT OR IGNORE INTO group_categories (category_name, created_at) VALUES (?, ?)", (cat, now))

    # 数据库迁移：为现有群组添加 category 字段（如果不存在）
    try:
        c.execute("SELECT category FROM groups LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE groups ADD COLUMN category TEXT DEFAULT '未分类'")
        print("✅ 已为 groups 表添加 category 字段")

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

def save_group(group_id: str, title: str, category: str = None):
    """
    保存或更新群组信息。
    如果指定 category，则使用该分类；否则保留原有分类或使用'未分类'
    """
    import time
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    try:
        # 如果没有指定分类，尝试获取原有分类
        if category is None:
            c.execute("SELECT category FROM groups WHERE group_id = ?", (group_id,))
            row = c.fetchone()
            category = row[0] if row else '未分类'

        c.execute("""
            INSERT OR REPLACE INTO groups (group_id, title, last_seen, category)
            VALUES (?, ?, ?, ?)
        """, (group_id, title, int(time.time()), category))

        conn.commit()

        c.execute("SELECT count(*) FROM groups")
        count = c.fetchone()[0]
        print(f"💾 [DB] 群组 {title} (分类: {category}) 已保存。当前数据库总群组数：{count}")

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

def get_all_groups_from_db(category: str = None):
    """
    获取群组列表（支持按分类筛选）
    返回字典列表：[{'id': ..., 'title': ..., 'category': ...}, ...]
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if category:
        c.execute("SELECT group_id, title, last_seen, category FROM groups WHERE category = ?", (category,))
    else:
        c.execute("SELECT group_id, title, last_seen, category FROM groups")

    rows = c.fetchall()
    conn.close()

    return [{"id": row["group_id"], "title": row["title"], "last_seen": row["last_seen"], "category": row["category"]} for row in rows]

def update_group_category(group_id: str, category: str):
    """更新群组分类"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    try:
        c.execute("UPDATE groups SET category = ? WHERE group_id = ?", (category, group_id))
        conn.commit()
        print(f"✅ 群组 {group_id} 分类已更新为: {category}")
        return True
    except Exception as e:
        print(f"❌ 更新分类失败: {e}")
        return False
    finally:
        conn.close()

def get_all_categories():
    """获取所有分类列表"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT category_name, description FROM group_categories ORDER BY category_id")
    rows = c.fetchall()
    conn.close()
    return [{"name": row[0], "description": row[1] or ""} for row in rows]

def add_category(category_name: str, description: str = ""):
    """添加新分类"""
    import time
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    try:
        c.execute("INSERT INTO group_categories (category_name, description, created_at) VALUES (?, ?, ?)",
                  (category_name, description, int(time.time())))
        conn.commit()
        print(f"✅ 已添加分类: {category_name}")
        return True
    except sqlite3.IntegrityError:
        print(f"❌ 分类已存在: {category_name}")
        return False
    finally:
        conn.close()

def delete_category(category_name: str):
    """删除分类（同时将该分类下的群组移到'未分类'）"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    try:
        # 先将该分类下的群组移到未分类
        c.execute("UPDATE groups SET category = '未分类' WHERE category = ?", (category_name,))
        # 删除分类
        c.execute("DELETE FROM group_categories WHERE category_name = ?", (category_name,))
        conn.commit()
        print(f"✅ 已删除分类: {category_name}")
        return True
    except Exception as e:
        print(f"❌ 删除分类失败: {e}")
        return False
    finally:
        conn.close()

def get_groups_by_category():
    """按分类统计群组数量"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT category, COUNT(*) as count 
        FROM groups 
        GROUP BY category 
        ORDER BY count DESC
    """)
    rows = c.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}
