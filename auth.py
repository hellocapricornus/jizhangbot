# auth.py - 修复导入问题

import sqlite3
import os
from telegram import Update  # 添加这个导入
from telegram.ext import ContextTypes  # 可选，如果需要的话

OWNER_ID = 8107909168  # 控制人ID

# 确定数据库路径 (必须与 db.py 一致)
DB_PATH = "bot.db"
if not os.path.isabs(DB_PATH):
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), DB_PATH)

def _get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    return conn

def init_operators_from_db():
    """
    启动时从数据库加载所有操作员到内存。
    需要在 main.py 的 init_db() 之后调用，或者直接在 import 时调用。
    """
    global operators
    try:
        conn = _get_db_connection()
        c = conn.cursor()
        # 确保表存在 (防御性编程)
        c.execute("""
            CREATE TABLE IF NOT EXISTS operators (
                user_id TEXT PRIMARY KEY,
                name TEXT
            )
        """)
        conn.commit()

        c.execute("SELECT user_id FROM operators")
        rows = c.fetchall()
        conn.close()

        # 转换为整数集合
        operators = {int(row[0]) for row in rows}
        print(f"✅ 已从数据库加载 {len(operators)} 名操作员: {operators}")
        return operators
    except Exception as e:
        print(f"❌ 加载操作员失败: {e}")
        operators = set()
        return operators

# 初始化内存集合
operators = set()
# 尝试立即加载 (如果 main.py 还没 init_db，这里可能会创建空表，没关系)
init_operators_from_db()

def is_authorized(user_id: int) -> bool:
    """是否是控制人或者操作人"""
    return user_id == OWNER_ID or user_id in operators

def add_operator(user_id: int):
    """添加操作员并同步到数据库"""
    if user_id in operators:
        return False # 已存在

    operators.add(user_id)

    # 写入数据库
    try:
        conn = _get_db_connection()
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO operators (user_id) VALUES (?)", (str(user_id),))
        conn.commit()
        conn.close()
        print(f"💾 [DB] 操作员 {user_id} 已持久化保存。")
    except Exception as e:
        print(f"❌ [DB Error] 保存操作员失败: {e}")
        # 如果数据库失败，内存中依然保留，但重启后会丢失
        operators.discard(user_id)

def remove_operator(user_id: int):
    """删除操作员并同步到数据库"""
    if user_id not in operators:
        return

    operators.discard(user_id)

    # 从数据库删除
    try:
        conn = _get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM operators WHERE user_id = ?", (str(user_id),))
        conn.commit()
        conn.close()
        print(f"🗑️ [DB] 操作员 {user_id} 已从数据库移除。")
    except Exception as e:
        print(f"❌ [DB Error] 删除操作员失败: {e}")

def list_operators():
    return list(operators)

# 可选：群组管理员检查函数（如果需要的话）
async def is_group_admin(app, chat_id: int, user_id: int) -> bool:
    """检查用户是否为群组管理员"""
    try:
        member = await app.bot.get_chat_member(chat_id, user_id)
        return member.status in ['administrator', 'creator']
    except Exception as e:
        print(f"检查管理员权限失败: {e}")
        return False
