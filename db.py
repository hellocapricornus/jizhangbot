# db.py

import sqlite3
import os
import time

DB_PATH = "bot.db"
if not os.path.isabs(DB_PATH):
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), DB_PATH)

def get_db_connection():
    """获取数据库连接"""
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 创建 operators 表
    c.execute("""
        CREATE TABLE IF NOT EXISTS operators (
            user_id TEXT PRIMARY KEY,
            name TEXT
        )
    """)

    # 创建 groups 表
    c.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            group_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            last_seen INTEGER DEFAULT 0,
            category TEXT DEFAULT '未分类'
        )
    """)

    # 创建分类表
    c.execute("""
        CREATE TABLE IF NOT EXISTS group_categories (
            category_id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_name TEXT UNIQUE NOT NULL,
            created_at INTEGER DEFAULT 0,
            description TEXT
        )
    """)

    # 初始化默认分类
    now = int(time.time())
    default_categories = ['未分类']
    for cat in default_categories:
        c.execute("INSERT OR IGNORE INTO group_categories (category_name, created_at) VALUES (?, ?)", (cat, now))

    # 数据库迁移：为现有群组添加 category 字段
    try:
        c.execute("SELECT category FROM groups LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE groups ADD COLUMN category TEXT DEFAULT '未分类'")
        print("✅ 已为 groups 表添加 category 字段")

    # ========== 新增：监控地址表 ==========
    c.execute("""
        CREATE TABLE IF NOT EXISTS monitored_addresses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT NOT NULL,
            chain_type TEXT NOT NULL,
            added_by INTEGER NOT NULL,
            added_at INTEGER NOT NULL,
            last_check INTEGER DEFAULT 0,
            last_tx_id TEXT,
            UNIQUE(address, chain_type)
        )
    """)

    # 新增：交易记录表
    c.execute("""
        CREATE TABLE IF NOT EXISTS address_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT NOT NULL,
            tx_id TEXT NOT NULL,
            from_addr TEXT,
            to_addr TEXT,
            amount REAL,
            timestamp INTEGER NOT NULL,
            notified INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()
    print(f"✅ 数据库初始化完成: {DB_PATH}")

# ========== 监控地址相关操作 ==========

def get_monitored_addresses(user_id: int = None):
    """获取监控地址，如果指定 user_id 则只返回该用户添加的地址"""
    conn = get_db_connection()
    c = conn.cursor()

    if user_id is not None:
        c.execute("SELECT id, address, chain_type, added_by, added_at, last_check FROM monitored_addresses WHERE added_by = ? ORDER BY added_at DESC", (user_id,))
    else:
        c.execute("SELECT id, address, chain_type, added_by, added_at, last_check FROM monitored_addresses ORDER BY added_at DESC")

    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "address": r[1], "chain_type": r[2], "added_by": r[3], "added_at": r[4], "last_check": r[5]} for r in rows]


def add_monitored_address(address: str, chain_type: str, added_by: int):
    """添加监控地址"""
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO monitored_addresses (address, chain_type, added_by, added_at, last_check)
            VALUES (?, ?, ?, ?, 0)
        """, (address, chain_type, added_by, int(time.time())))
        conn.commit()
        return True
    except Exception as e:
        print(f"添加监控地址失败: {e}")
        return False
    finally:
        conn.close()


def remove_monitored_address(address_id: int):
    """删除监控地址"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM monitored_addresses WHERE id = ?", (address_id,))
    conn.commit()
    conn.close()
    return True


def update_address_last_check(address: str, last_check: int):
    """更新地址最后检查时间"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE monitored_addresses SET last_check = ? WHERE address = ?", (last_check, address))
    conn.commit()
    conn.close()


def add_transaction_record(address: str, tx_id: str, from_addr: str, to_addr: str, amount: float, timestamp: int):
    """添加交易记录"""
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO address_transactions (address, tx_id, from_addr, to_addr, amount, timestamp, notified)
            VALUES (?, ?, ?, ?, ?, ?, 0)
        """, (address, tx_id, from_addr, to_addr, amount, timestamp))
        conn.commit()
        return True
    except Exception as e:
        print(f"添加交易记录失败: {e}")
        return False
    finally:
        conn.close()


def is_tx_notified(tx_id: str) -> bool:
    """检查交易是否已通知"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT notified FROM address_transactions WHERE tx_id = ?", (tx_id,))
    row = c.fetchone()
    conn.close()
    return row is not None and row[0] == 1


def mark_tx_notified(tx_id: str):
    """标记交易为已通知"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE address_transactions SET notified = 1 WHERE tx_id = ?", (tx_id,))
    conn.commit()
    conn.close()


# ========== 原有函数保持不变 ==========

def save_group(group_id: str, title: str, category: str = None):
    """保存或更新群组信息"""
    import time
    conn = get_db_connection()
    c = conn.cursor()

    try:
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
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM groups WHERE group_id = ?", (group_id,))
    conn.commit()
    count = c.execute("SELECT count(*) FROM groups").fetchone()[0]
    print(f"🗑️ [DB] 群组 {group_id} 已删除。剩余群组数：{count}")
    conn.close()


def get_all_groups_from_db(category: str = None):
    conn = get_db_connection()
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
    conn = get_db_connection()
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
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT category_name, description FROM group_categories ORDER BY category_id")
    rows = c.fetchall()
    conn.close()
    return [{"name": row[0], "description": row[1] or ""} for row in rows]


def add_category(category_name: str, description: str = ""):
    import time
    conn = get_db_connection()
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
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("UPDATE groups SET category = '未分类' WHERE category = ?", (category_name,))
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
    conn = get_db_connection()
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
