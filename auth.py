import sqlite3
import os
import time
from typing import Dict, Optional
from contextlib import contextmanager

from telegram import Update
from telegram.ext import ContextTypes

from config import OWNER_ID
from logger import bot_logger as logger

DB_PATH = "bot.db"
if not os.path.isabs(DB_PATH):
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), DB_PATH)

# 存储格式：{user_id: {"id": int, "username": str, "first_name": str, "last_name": str}}
operators: Dict[int, dict] = {}
temp_operators: Dict[int, dict] = {}


@contextmanager
def _safe_db_connection(db_path: str = DB_PATH):
    """安全的数据库连接上下文管理器，确保异常时也能关闭连接"""
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        yield conn
    except Exception as e:
        logger.error(f"数据库操作失败: {e}")
        raise
    finally:
        if conn:
            try:
                conn.close()
            except Exception as e:
                logger.error(f"关闭数据库连接失败: {e}")


def _get_db_connection() -> sqlite3.Connection:
    """获取数据库连接（保留用于向后兼容，推荐使用 _safe_db_connection）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_operators_from_db() -> Dict[int, dict]:
    """启动时从数据库加载所有操作员到内存（自动迁移旧数据）"""
    global operators
    try:
        with _safe_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS operators (
                    user_id TEXT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT
                )
            """)
            conn.commit()
            c.execute("PRAGMA table_info(operators)")
            columns = [col[1] for col in c.fetchall()]
            if 'username' not in columns:
                logger.info("检测到旧数据格式，正在添加新字段...")
                c.execute("ALTER TABLE operators ADD COLUMN username TEXT")
                c.execute("ALTER TABLE operators ADD COLUMN first_name TEXT")
                c.execute("ALTER TABLE operators ADD COLUMN last_name TEXT")
                conn.commit()
                logger.info("数据库结构已更新")
            c.execute("SELECT user_id, username, first_name, last_name FROM operators")
            rows = c.fetchall()

        operators = {}
        for row in rows:
            user_id = int(row['user_id'])
            operators[user_id] = {
                "id": user_id,
                "username": row['username'],
                "first_name": row['first_name'],
                "last_name": row['last_name']
            }
        logger.info(f"已从数据库加载 {len(operators)} 名操作员")
        for uid, info in operators.items():
            name = info.get('first_name', '未知')
            username = f"(@{info['username']})" if info.get('username') else ""
            logger.info(f"   - {name} {username} (ID: {uid})")
        return operators
    except Exception as e:
        logger.error(f"加载操作员失败: {e}")
        operators = {}
        return operators


# ========== 临时操作人相关函数 ==========

def init_temp_operators_table():
    """初始化临时操作人表"""
    try:
        with _safe_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS temp_operators (
                    user_id TEXT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    added_at INTEGER,
                    added_by INTEGER
                )
            """)
            conn.commit()
        logger.info("临时操作人表初始化完成")
        return True
    except Exception as e:
        logger.error(f"初始化临时操作人表失败: {e}")
        return False


def init_temp_operators_from_db():
    """从数据库加载临时操作人"""
    global temp_operators
    try:
        with _safe_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS temp_operators (
                    user_id TEXT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    added_at INTEGER,
                    added_by INTEGER
                )
            """)
            conn.commit()
            c.execute("SELECT user_id, username, first_name, last_name FROM temp_operators")
            rows = c.fetchall()

        temp_operators = {}
        for row in rows:
            user_id = int(row['user_id'])
            temp_operators[user_id] = {
                "id": user_id,
                "username": row['username'],
                "first_name": row['first_name'],
                "last_name": row['last_name']
            }
        logger.info(f"已从数据库加载 {len(temp_operators)} 名临时操作人")
        return temp_operators
    except Exception as e:
        logger.error(f"加载临时操作人失败: {e}")
        temp_operators = {}
        return temp_operators


# ========== 初始化调用（放在函数定义之后）==========
init_temp_operators_table()
init_operators_from_db()
init_temp_operators_from_db()


async def add_operator(user_id: int, context: ContextTypes.DEFAULT_TYPE = None) -> bool:
    """添加操作员并同步到数据库"""
    if user_id in operators:
        return False

    username = None
    first_name = None
    last_name = None

    if context:
        try:
            bot = context.bot
            user = await bot.get_chat(user_id)
            username = user.username
            first_name = user.first_name
            last_name = user.last_name
            logger.info(f"获取到用户信息: {first_name} (@{username})")
        except Exception as e:
            logger.warning(f"无法获取用户 {user_id} 的详细信息: {e}")

    operators[user_id] = {
        "id": user_id,
        "username": username,
        "first_name": first_name,
        "last_name": last_name
    }

    try:
        with _safe_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT OR REPLACE INTO operators (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
                (str(user_id), username, first_name, last_name)
            )
            conn.commit()
        logger.info(f"[DB] 操作员 {user_id} 已持久化保存。")
        return True
    except Exception as e:
        logger.error(f"[DB Error] 保存操作员失败: {e}")
        operators.pop(user_id, None)
        return False


def remove_operator(user_id: int) -> bool:
    """删除操作员并同步到数据库"""
    if user_id not in operators:
        return False

    operators.pop(user_id, None)

    try:
        with _safe_db_connection() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM operators WHERE user_id = ?", (str(user_id),))
            conn.commit()
        logger.info(f"[DB] 操作员 {user_id} 已从数据库移除。")
        return True
    except Exception as e:
        logger.error(f"[DB Error] 删除操作员失败: {e}")
        return False


def list_operators() -> Dict[int, dict]:
    """返回所有操作员字典（包含详细信息）"""
    return operators


def get_operator_info(user_id: int) -> Optional[dict]:
    """获取单个操作员信息"""
    return operators.get(user_id)


def get_operators_list_text() -> str:
    """生成格式化的操作员列表文本（包含正式操作人和临时操作人）"""
    text = "📋 **操作人列表**\n" + "━" * 20 + "\n\n"

    text += "👑 **正式操作人**\n"
    if operators:
        for user_id, info in operators.items():
            display_name = []
            if info.get("first_name"):
                display_name.append(info["first_name"])
            if info.get("last_name"):
                display_name.append(info["last_name"])
            name_str = " ".join(display_name) if display_name else "未设置昵称"
            username_str = f"(@{info['username']})" if info.get("username") else ""
            text += f"  👤 {name_str} {username_str}\n"
            text += f"     🆔 ID: `{user_id}`\n"
    else:
        text += "  📭 暂无正式操作人\n"

    text += "\n" + "━" * 20 + "\n\n"

    text += "👥 **临时操作人**（仅记账权限）\n"
    if temp_operators:
        for user_id, info in temp_operators.items():
            display_name = []
            if info.get("first_name"):
                display_name.append(info["first_name"])
            if info.get("last_name"):
                display_name.append(info["last_name"])
            name_str = " ".join(display_name) if display_name else "未设置昵称"
            username_str = f"(@{info['username']})" if info.get("username") else ""
            text += f"  👤 {name_str} {username_str}\n"
            text += f"     🆔 ID: `{user_id}`\n"
    else:
        text += "  📭 暂无临时操作人\n"

    return text


async def update_all_operators_info(context: ContextTypes.DEFAULT_TYPE):
    """更新所有操作员的详细信息（用于补充用户信息）"""
    if not operators:
        logger.info("没有操作员需要更新")
        return 0

    updated_count = 0
    failed_count = 0
    logger.info(f"开始更新 {len(operators)} 个操作员的信息...")

    for user_id in list(operators.keys()):
        try:
            user = await context.bot.get_chat(user_id)
            operators[user_id] = {
                "id": user_id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name
            }

            with _safe_db_connection() as conn:
                c = conn.cursor()
                c.execute(
                    "INSERT OR REPLACE INTO operators (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
                    (str(user_id), user.username, user.first_name, user.last_name)
                )
                conn.commit()

            updated_count += 1
            logger.info(f"已更新: {user.first_name} (@{user.username}) - ID: {user_id}")
        except Exception as e:
            failed_count += 1
            logger.error(f"更新失败 ID {user_id}: {e}")

    logger.info(f"更新完成！成功: {updated_count}, 失败: {failed_count}")
    return updated_count


async def cmd_update_operator_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """命令处理：更新操作人信息（仅控制人可用）"""
    user_id = update.effective_user.id

    if user_id != OWNER_ID:
        await update.message.reply_text("❌ 只有控制人可以使用此命令")
        return

    await update.message.reply_text("🔄 正在更新操作人信息，请稍候...")
    count = await update_all_operators_info(context)

    if count > 0:
        await update.message.reply_text(f"✅ 已成功更新 {count} 个操作人的信息")
        text = get_operators_list_text()
        await update.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text("⚠️ 没有操作人被更新，或更新失败")


def is_temp_authorized(user_id: int) -> bool:
    """检查是否是临时操作人（仅记账权限）"""
    return user_id in temp_operators


def is_authorized(user_id: int, require_full_access: bool = False) -> bool:
    """
    检查用户权限
    - require_full_access=True：需要控制人或正式操作员（用于所有管理功能）
    - require_full_access=False：记账权限即可（控制人、正式操作员、临时操作员）
    """
    if user_id == OWNER_ID:
        return True
    if require_full_access:
        return user_id in operators
    return user_id in operators or user_id in temp_operators


async def add_temp_operator(user_id: int, added_by: int, context: ContextTypes.DEFAULT_TYPE = None) -> bool:
    """添加临时操作人"""
    if user_id in temp_operators:
        return False

    username = None
    first_name = None
    last_name = None

    if context:
        try:
            user = await context.bot.get_chat(user_id)
            username = user.username
            first_name = user.first_name
            last_name = user.last_name
        except Exception as e:
            logger.warning(f"无法获取用户 {user_id} 的详细信息: {e}")

    temp_operators[user_id] = {
        "id": user_id,
        "username": username,
        "first_name": first_name,
        "last_name": last_name
    }

    try:
        with _safe_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT OR REPLACE INTO temp_operators (user_id, username, first_name, last_name, added_at, added_by) VALUES (?, ?, ?, ?, ?, ?)",
                (str(user_id), username, first_name, last_name, int(time.time()), added_by)
            )
            conn.commit()
        logger.info(f"[DB] 临时操作员 {user_id} 已持久化保存。")
        return True
    except Exception as e:
        logger.error(f"[DB Error] 保存临时操作员失败: {e}")
        temp_operators.pop(user_id, None)
        return False


def remove_temp_operator(user_id: int) -> bool:
    """删除临时操作人"""
    if user_id not in temp_operators:
        return False

    temp_operators.pop(user_id, None)

    try:
        with _safe_db_connection() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM temp_operators WHERE user_id = ?", (str(user_id),))
            conn.commit()
        logger.info(f"[DB] 临时操作员 {user_id} 已从数据库移除。")
        return True
    except Exception as e:
        logger.error(f"[DB Error] 删除临时操作员失败: {e}")
        return False


def get_temp_operators_list_text() -> str:
    """生成临时操作人列表文本"""
    if not temp_operators:
        return "📭 当前没有临时操作人"

    text = "👥 临时操作人列表：\n" + "━" * 20 + "\n"
    for user_id, info in temp_operators.items():
        display_name = []
        if info.get("first_name"):
            display_name.append(info["first_name"])
        if info.get("last_name"):
            display_name.append(info["last_name"])
        name_str = " ".join(display_name) if display_name else "未设置昵称"
        username_str = f"(@{info['username']})" if info.get("username") else ""
        text += f"👤 {name_str} {username_str}\n"
        text += f"🆔 ID: `{user_id}`\n"
        text += "━" * 20 + "\n"

    return text


def is_admin(user_id: int) -> bool:
    """控制人或正式操作员"""
    return is_authorized(user_id, require_full_access=True)


def is_operator_or_temp(user_id: int) -> bool:
    """控制人、正式操作员或临时操作员"""
    return is_authorized(user_id, require_full_access=False)
