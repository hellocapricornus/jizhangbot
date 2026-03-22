# accounting.py - 完整的记账功能（包含所有函数）

import re
import time
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler
from auth import is_authorized

# 设置北京时区 (UTC+8)
BEIJING_TZ = timezone(timedelta(hours=8))

def beijing_time(timestamp: int) -> datetime:
    """将时间戳转换为北京时间"""
    return datetime.fromtimestamp(timestamp, tz=BEIJING_TZ)

# 状态定义
ACCOUNTING_DATE_SELECT = 1
ACCOUNTING_CONFIRM_CLEAR = 2
ACCOUNTING_CONFIRM_CLEAR_ALL = 3

class AccountingManager:
    """记账管理器"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_conn(self):
        """获取数据库连接，设置超时避免锁"""
        return sqlite3.connect(self.db_path, timeout=10)

    def init_tables(self):
        """初始化记账相关的表"""
        conn = self._get_conn()
        c = conn.cursor()

        # 群组配置表
        c.execute("""
            CREATE TABLE IF NOT EXISTS group_accounting_config (
                group_id TEXT PRIMARY KEY,
                fee_rate REAL DEFAULT 0.0,
                exchange_rate REAL DEFAULT 1.0,
                session_id TEXT,
                session_start_time INTEGER DEFAULT 0,
                session_end_time INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                updated_at INTEGER DEFAULT 0
            )
        """)

        # 记账记录表
        c.execute("""
            CREATE TABLE IF NOT EXISTS accounting_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                first_name TEXT,
                record_type TEXT NOT NULL,
                amount REAL NOT NULL,
                amount_usdt REAL NOT NULL,
                description TEXT,
                created_at INTEGER NOT NULL,
                date TEXT NOT NULL
            )
        """)

        # 已结束的会话表
        c.execute("""
            CREATE TABLE IF NOT EXISTS accounting_sessions (
                session_id TEXT PRIMARY KEY,
                group_id TEXT NOT NULL,
                start_time INTEGER NOT NULL,
                end_time INTEGER NOT NULL,
                date TEXT NOT NULL,
                fee_rate REAL DEFAULT 0.0,
                exchange_rate REAL DEFAULT 1.0
            )
        """)

        # 添加用户追踪表
        c.execute("""
            CREATE TABLE IF NOT EXISTS group_users (
                group_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                last_seen INTEGER NOT NULL,
                PRIMARY KEY (group_id, user_id)
            )
        """)

        conn.commit()
        conn.close()

    def get_or_create_session(self, group_id: str) -> Dict:
        """获取或创建当前会话"""
        conn = self._get_conn()
        c = conn.cursor()

        try:
            # 查找活跃会话
            c.execute("""
                SELECT fee_rate, exchange_rate, session_id, session_start_time, is_active
                FROM group_accounting_config 
                WHERE group_id = ? AND is_active = 1
            """, (group_id,))
            row = c.fetchone()

            if row:
                conn.close()
                return {
                    'session_id': row[2],
                    'fee_rate': row[0],
                    'exchange_rate': row[1],
                    'start_time': row[3],
                    'is_active': True
                }

            # 创建新会话
            now = int(time.time())
            session_id = f"{group_id}_{now}"

            # 先删除可能存在的旧非活跃会话
            c.execute("DELETE FROM group_accounting_config WHERE group_id = ?", (group_id,))

            # 插入新会话
            c.execute("""
                INSERT INTO group_accounting_config 
                (group_id, fee_rate, exchange_rate, session_id, session_start_time, is_active, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
            """, (group_id, 0.0, 1.0, session_id, now, now))

            conn.commit()
            conn.close()

            return {
                'session_id': session_id,
                'fee_rate': 0.0,
                'exchange_rate': 1.0,
                'start_time': now,
                'is_active': True
            }
        except Exception as e:
            print(f"获取/创建会话失败: {e}")
            conn.close()
            return {
                'session_id': f"{group_id}_{int(time.time())}",
                'fee_rate': 0.0,
                'exchange_rate': 1.0,
                'start_time': int(time.time()),
                'is_active': True
            }

    def end_session(self, group_id: str) -> Dict:
        """结束当前会话"""
        conn = self._get_conn()
        c = conn.cursor()
        now = int(time.time())

        try:
            c.execute("""
                SELECT session_id, fee_rate, exchange_rate, session_start_time
                FROM group_accounting_config 
                WHERE group_id = ? AND is_active = 1
            """, (group_id,))
            row = c.fetchone()

            if not row:
                conn.close()
                return None

            session_id, fee_rate, exchange_rate, start_time = row

            c.execute("""
                SELECT record_type, SUM(amount_usdt)
                FROM accounting_records
                WHERE group_id = ? AND session_id = ?
                GROUP BY record_type
            """, (group_id, session_id))
            stats_rows = c.fetchall()

            income_usdt = 0
            expense_usdt = 0
            for stat in stats_rows:
                if stat[0] == 'income':
                    income_usdt = stat[1] or 0
                else:
                    expense_usdt = stat[1] or 0

            # ✅ 使用北京时间获取会话日期
            start_beijing = beijing_time(start_time)
            date_str = start_beijing.strftime('%Y-%m-%d')
            
            c.execute("""
                INSERT OR REPLACE INTO accounting_sessions 
                (session_id, group_id, start_time, end_time, date, fee_rate, exchange_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (session_id, group_id, start_time, now, date_str, fee_rate, exchange_rate))

            c.execute("""
                UPDATE group_accounting_config 
                SET is_active = 0, session_end_time = ?, updated_at = ?
                WHERE group_id = ? AND is_active = 1
            """, (now, now, group_id))

            conn.commit()
            conn.close()

            return {
                'session_id': session_id,
                'fee_rate': fee_rate,
                'exchange_rate': exchange_rate,
                'income_usdt': income_usdt,
                'expense_usdt': expense_usdt
            }
        except Exception as e:
            print(f"结束会话失败: {e}")
            conn.close()
            return None

    def get_current_stats(self, group_id: str) -> Dict:
        """获取当前会话统计"""
        try:
            session = self.get_or_create_session(group_id)

            conn = self._get_conn()
            c = conn.cursor()

            # 注意：这里使用 SUM(amount) 会自动处理正负数
            c.execute("""
                SELECT record_type, SUM(amount), SUM(amount_usdt), COUNT(*)
                FROM accounting_records
                WHERE group_id = ? AND session_id = ?
                GROUP BY record_type
            """, (group_id, session['session_id']))
            rows = c.fetchall()
            conn.close()

            income_total = 0
            income_usdt = 0
            income_count = 0
            expense_total = 0
            expense_usdt = 0
            expense_count = 0

            for row in rows:
                if row[0] == 'income':
                    income_total = row[1] or 0  # 这里自动累加正负数
                    income_usdt = row[2] or 0
                    income_count = row[3] or 0
                else:
                    expense_total = row[1] or 0
                    expense_usdt = row[2] or 0
                    expense_count = row[3] or 0

            return {
                'fee_rate': session['fee_rate'],
                'exchange_rate': session['exchange_rate'],
                'income_total': income_total,  # 已经是净额（正数+负数）
                'income_usdt': income_usdt,
                'income_count': income_count,
                'expense_total': expense_total,
                'expense_usdt': expense_usdt,
                'expense_count': expense_count,
                'pending_usdt': income_usdt - expense_usdt
            }
        except Exception as e:
            print(f"获取当前统计失败: {e}")
            return {
                'fee_rate': 0,
                'exchange_rate': 1,
                'income_total': 0,
                'income_usdt': 0,
                'income_count': 0,
                'expense_total': 0,
                'expense_usdt': 0,
                'expense_count': 0,
                'pending_usdt': 0
            }

    def get_current_records(self, group_id: str) -> List[Dict]:
        """获取当前会话记录"""
        try:
            session = self.get_or_create_session(group_id)

            conn = self._get_conn()
            c = conn.cursor()

            c.execute("""
                SELECT record_type, amount, amount_usdt, description, created_at, username, user_id
                FROM accounting_records
                WHERE group_id = ? AND session_id = ?
                ORDER BY created_at ASC
            """, (group_id, session['session_id']))
            rows = c.fetchall()
            conn.close()

            records = []
            for row in rows:
                records.append({
                    'type': row[0],
                    'amount': row[1],
                    'amount_usdt': row[2],
                    'description': row[3],
                    'created_at': row[4],
                    'first_name': row[6],
                    'user_id': row[7]
                })
            return records
        except Exception as e:
            print(f"获取当前记录失败: {e}")
            return []

    def add_record(self, group_id: str, user_id: int, username: str, first_name: str, 
                   record_type: str, amount: float, description: str = "") -> bool:
        """添加记账记录"""
        try:
            session = self.get_or_create_session(group_id)

            if record_type == 'income':
                raw_usdt = amount / session['exchange_rate']
                amount_usdt = raw_usdt * (1 - session['fee_rate'] / 100)
            else:
                amount_usdt = amount

            now = int(time.time())
            # 使用北京时间获取日期
            beijing_dt = beijing_time(now)
            date_str = beijing_dt.strftime('%Y-%m-%d')  # 改用北京时间

            conn = self._get_conn()
            c = conn.cursor()
            c.execute("""
                INSERT INTO accounting_records 
                (group_id, session_id, user_id, username, first_name, record_type, amount, amount_usdt, 
                 description, created_at, date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (group_id, session['session_id'], user_id, username or "", first_name or "",  record_type, amount, 
                  amount_usdt, description, now, date_str))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"添加记录失败: {e}")
            return False

    def set_fee_rate(self, group_id: str, rate: float) -> bool:
        """设置手续费率"""
        try:
            conn = self._get_conn()
            c = conn.cursor()
            now = int(time.time())
            c.execute("""
                UPDATE group_accounting_config 
                SET fee_rate = ?, updated_at = ?
                WHERE group_id = ? AND is_active = 1
            """, (rate, now, group_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"设置费率失败: {e}")
            return False

    def set_exchange_rate(self, group_id: str, rate: float) -> bool:
        """设置汇率"""
        try:
            conn = self._get_conn()
            c = conn.cursor()
            now = int(time.time())
            c.execute("""
                UPDATE group_accounting_config 
                SET exchange_rate = ?, updated_at = ?
                WHERE group_id = ? AND is_active = 1
            """, (rate, now, group_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"设置汇率失败: {e}")
            return False

    def get_today_stats(self, group_id: str) -> Dict:
        """获取今日统计"""
        # 使用北京时间获取今日日期
        beijing_now = beijing_time(int(time.time()))
        today = beijing_now.strftime('%Y-%m-%d')  # ✅ 改用北京时间

        try:
            conn = self._get_conn()
            c = conn.cursor()

            c.execute("""
                SELECT record_type, SUM(amount), SUM(amount_usdt), COUNT(*)
                FROM accounting_records
                WHERE group_id = ? AND date = ?
                GROUP BY record_type
            """, (group_id, today))
            rows = c.fetchall()
            conn.close()

            income_total = 0
            income_usdt = 0
            income_count = 0
            expense_total = 0
            expense_usdt = 0
            expense_count = 0

            for row in rows:
                if row[0] == 'income':
                    income_total = row[1] or 0
                    income_usdt = row[2] or 0
                    income_count = row[3] or 0
                else:
                    expense_total = row[1] or 0
                    expense_usdt = row[2] or 0
                    expense_count = row[3] or 0

            session = self.get_or_create_session(group_id)

            return {
                'fee_rate': session['fee_rate'],
                'exchange_rate': session['exchange_rate'],
                'income_total': income_total,
                'income_usdt': income_usdt,
                'income_count': income_count,
                'expense_total': expense_total,
                'expense_usdt': expense_usdt,
                'expense_count': expense_count,
                'pending_usdt': income_usdt - expense_usdt
            }
        except Exception as e:
            print(f"获取今日统计失败: {e}")
            return self.get_current_stats(group_id)

    def get_total_stats(self, group_id: str) -> Dict:
        """获取总计统计"""
        try:
            conn = self._get_conn()
            c = conn.cursor()

            c.execute("""
                SELECT record_type, SUM(amount), SUM(amount_usdt), COUNT(*)
                FROM accounting_records
                WHERE group_id = ?
                GROUP BY record_type
            """, (group_id,))
            rows = c.fetchall()
            conn.close()

            income_total = 0
            income_usdt = 0
            income_count = 0
            expense_total = 0
            expense_usdt = 0
            expense_count = 0

            for row in rows:
                if row[0] == 'income':
                    income_total = row[1] or 0
                    income_usdt = row[2] or 0
                    income_count = row[3] or 0
                else:
                    expense_total = row[1] or 0
                    expense_usdt = row[2] or 0
                    expense_count = row[3] or 0

            session = self.get_or_create_session(group_id)

            return {
                'fee_rate': session['fee_rate'],
                'exchange_rate': session['exchange_rate'],
                'income_total': income_total,
                'income_usdt': income_usdt,
                'income_count': income_count,
                'expense_total': expense_total,
                'expense_usdt': expense_usdt,
                'expense_count': expense_count,
                'pending_usdt': income_usdt - expense_usdt
            }
        except Exception as e:
            print(f"获取总计统计失败: {e}")
            return self.get_current_stats(group_id)

    def get_today_records(self, group_id: str) -> List[Dict]:
        """获取今日所有记录"""
        # 使用北京时间获取今日日期
        beijing_now = beijing_time(int(time.time()))
        today = beijing_now.strftime('%Y-%m-%d')  # ✅ 改用北京时间

        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("""
                SELECT record_type, amount, amount_usdt, description, created_at, username, user_id
                FROM accounting_records
                WHERE group_id = ? AND date = ?
                ORDER BY created_at ASC
            """, (group_id, today))
            rows = c.fetchall()
            conn.close()

            records = []
            for row in rows:
                records.append({
                    'type': row[0],
                    'amount': row[1],
                    'amount_usdt': row[2],
                    'description': row[3],
                    'created_at': row[4],
                    'username': row[5]
                    'first_name': row[6],
                    'user_id': row[7]
                })
            return records
        except Exception as e:
            print(f"获取今日记录失败: {e}")
            return []

    def get_total_records(self, group_id: str) -> List[Dict]:
        """获取所有记录"""
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("""
                SELECT record_type, amount, amount_usdt, description, created_at, username, date, user_id
                FROM accounting_records
                WHERE group_id = ?
                ORDER BY created_at ASC
            """, (group_id,))
            rows = c.fetchall()
            conn.close()

            records = []
            for row in rows:
                records.append({
                    'type': row[0],
                    'amount': row[1],
                    'amount_usdt': row[2],
                    'description': row[3],
                    'created_at': row[4],
                    'username': row[5],
                    'first_name': row[6],
                    'user_id': row[7]
                })
            return records
        except Exception as e:
            print(f"获取总记录失败: {e}")
            return []

    def get_sessions_by_date(self, group_id: str) -> List[Dict]:
        """获取按日期分组的历史会话"""
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("""
                SELECT DISTINCT date
                FROM accounting_sessions
                WHERE group_id = ?
                ORDER BY date DESC
                LIMIT 30
            """, (group_id,))
            rows = c.fetchall()
            conn.close()

            dates = []
            for row in rows:
                dates.append({'date': row[0]})
            return dates
        except Exception as e:
            print(f"获取历史日期失败: {e}")
            return []

    def get_records_by_date(self, group_id: str, date_str: str) -> List[Dict]:
        """获取指定日期的所有记录"""
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("""
                SELECT record_type, amount, amount_usdt, description, created_at, username, user_id
                FROM accounting_records
                WHERE group_id = ? AND date = ?
                ORDER BY created_at ASC
            """, (group_id, date_str))
            rows = c.fetchall()
            conn.close()

            records = []
            for row in rows:
                records.append({
                    'type': row[0],
                    'amount': row[1],
                    'amount_usdt': row[2],
                    'description': row[3],
                    'created_at': row[4],
                    'username': row[5]
                    'first_name': row[6],
                    'user_id': row[7]
                })
            return records
        except Exception as e:
            print(f"获取日期记录失败: {e}")
            return []

    def get_stats_by_date(self, group_id: str, date_str: str) -> Dict:
        """获取指定日期的统计"""
        try:
            conn = self._get_conn()
            c = conn.cursor()

            c.execute("""
                SELECT record_type, SUM(amount), SUM(amount_usdt), COUNT(*)
                FROM accounting_records
                WHERE group_id = ? AND date = ?
                GROUP BY record_type
            """, (group_id, date_str))
            rows = c.fetchall()
            conn.close()

            income_total = 0
            income_usdt = 0
            income_count = 0
            expense_total = 0
            expense_usdt = 0
            expense_count = 0

            for row in rows:
                if row[0] == 'income':
                    income_total = row[1] or 0
                    income_usdt = row[2] or 0
                    income_count = row[3] or 0
                else:
                    expense_total = row[1] or 0
                    expense_usdt = row[2] or 0
                    expense_count = row[3] or 0

            return {
                'income_total': income_total,
                'income_usdt': income_usdt,
                'income_count': income_count,
                'expense_total': expense_total,
                'expense_usdt': expense_usdt,
                'expense_count': expense_count,
                'pending_usdt': income_usdt - expense_usdt
            }
        except Exception as e:
            print(f"获取日期统计失败: {e}")
            return {
                'income_total': 0,
                'income_usdt': 0,
                'income_count': 0,
                'expense_total': 0,
                'expense_usdt': 0,
                'expense_count': 0,
                'pending_usdt': 0
            }

    def clear_current_session(self, group_id: str) -> bool:
        """清空当前会话"""
        try:
            session = self.get_or_create_session(group_id)
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("DELETE FROM accounting_records WHERE group_id = ? AND session_id = ?", 
                      (group_id, session['session_id']))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"清空记录失败: {e}")
            return False

    def clear_all_records(self, group_id: str) -> bool:
        """清空群组的所有账单记录（包括当前会话和历史会话）"""
        try:
            conn = self._get_conn()
            c = conn.cursor()

            # 获取当前会话ID
            session = self.get_or_create_session(group_id)

            # 删除当前会话的所有记录
            c.execute("DELETE FROM accounting_records WHERE group_id = ?", (group_id,))

            # 删除历史会话记录
            c.execute("DELETE FROM accounting_sessions WHERE group_id = ?", (group_id,))

            # 重置群组配置（保留但重置费率汇率）
            c.execute("""
                UPDATE group_accounting_config 
                SET fee_rate = 0, exchange_rate = 1, updated_at = ?
                WHERE group_id = ?
            """, (int(time.time()), group_id))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"清空所有记录失败: {e}")
            return False

    def update_user_info(self, group_id: str, user_id: int, username: str, 
                         first_name: str, last_name: str = "") -> Tuple[bool, str, str]:
        """
        更新或添加用户信息
        返回: (是否有变更, 旧昵称, 新昵称)
        """
        try:
            conn = self._get_conn()
            c = conn.cursor()
            now = int(time.time())

            # 获取旧信息
            c.execute("""
                SELECT username, first_name, last_name
                FROM group_users
                WHERE group_id = ? AND user_id = ?
            """, (group_id, user_id))
            old = c.fetchone()

            old_username = None
            old_first_name = None
            old_display_name = None
            change_type = None
            
            if old:
                old_username = old[0] or ""
                old_first_name = old[1] or ""
                old_last_name = old[2] or ""
                # 旧的显示名称
                if old_username:
                    old_display_name = f"{old_first_name} (@{old_username})"
                else:
                    old_display_name = old_first_name

            # 新的显示名称
            if username:
                new_display_name = f"{first_name} (@{username})"
            else:
                new_display_name = first_name

            # 更新或插入
            c.execute("""
                INSERT OR REPLACE INTO group_users 
                (group_id, user_id, username, first_name, last_name, last_seen)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (group_id, user_id, username or "", first_name or "", last_name or "", now))

            conn.commit()
            conn.close()

            # 检查变更类型
            if old:
                if old_username != (username or "") and old_first_name != (first_name or ""):
                    change_type = "昵称和用户名"
                elif old_username != (username or ""):
                    change_type = "用户名"
                elif old_first_name != (first_name or ""):
                    change_type = "昵称"

            if change_type:
                return True, old_display_name or first_name, new_display_name, change_type

            return False, "", "", ""
        except Exception as e:
            print(f"更新用户信息失败: {e}")
            return False, "", "", ""


# 全局实例
accounting_manager = None

def init_accounting(db_path: str):
    """初始化记账模块"""
    global accounting_manager
    accounting_manager = AccountingManager(db_path)
    accounting_manager.init_tables()


# --- 格式化账单函数 ---
def format_bill_message(stats: Dict, records: List[Dict], title: str = "当前账单") -> str:
    """格式化账单消息"""
    message = f"📊 **{title}**\n\n"

    # 分离入款和出款记录
    income_records = [r for r in records if r['type'] == 'income']
    expense_records = [r for r in records if r['type'] == 'expense']

    # 入款记录（只显示最新的8条，倒序显示）
    if income_records:
        # 按时间倒序排序，最新的在前
        income_records_sorted = sorted(income_records, key=lambda x: x['created_at'], reverse=True)
        display_income = income_records_sorted[:8]  # 只取前8条
        total_income_count = len(income_records)

        message += f"📈 **入款 {total_income_count} 笔**"
        if total_income_count > 8:
            message += f" (显示最新8条)"
        message += "\n"

        for r in display_income:
            # 使用北京时间
            dt = beijing_time(r['created_at'])
            time_str = dt.strftime('%H:%M')
            amount = r['amount']
            amount_usdt = r['amount_usdt']
            first_name = r['first_name'] or "用户"
            user_id = r['user_id']

            # 构建可点击的昵称链接
            mention = f"[{first_name}](tg://user?id={user_id})"

            # 显示金额，如果是负数则显示减号，并添加操作者
            if amount < 0:
                message += f"`{time_str} {amount:.2f} = {amount_usdt:.2f} USDT` {mention}\n"
            else:
                message += f"`{time_str} +{amount:.2f} = {amount_usdt:.2f} USDT` {mention}\n"

        if total_income_count > 8:
            message += f"`... 还有 {total_income_count - 8} 条记录`\n"
        message += "\n"
    else:
        message += "📈 **入款 0 笔**\n\n"

    # 出款记录（只显示最新的8条，倒序显示）
    if expense_records:
        # 按时间倒序排序，最新的在前
        expense_records_sorted = sorted(expense_records, key=lambda x: x['created_at'], reverse=True)
        display_expense = expense_records_sorted[:8]  # 只取前8条
        total_expense_count = len(expense_records)

        message += f"📉 **出款 {total_expense_count} 笔**"
        if total_expense_count > 8:
            message += f" (显示最新8条)"
        message += "\n"

        for r in display_expense:
            # 使用北京时间
            dt = beijing_time(r['created_at'])
            time_str = dt.strftime('%H:%M')
            amount = r['amount']
            first_name = r['first_name'] or "用户"
            user_id = r['user_id']

            mention = f"[{first_name}](tg://user?id={user_id})"

            # 显示金额，如果是负数则显示减号，并添加操作者
            if amount < 0:
                message += f"`{time_str} {amount:.2f} USDT` {mention}\n"
            else:
                message += f"`{time_str} +{amount:.2f} USDT` {mention}\n"

        if total_expense_count > 8:
            message += f"`... 还有 {total_expense_count - 8} 条记录`\n"
        message += "\n"
    else:
        message += "📉 **出款 0 笔**\n\n"

    # 统计信息
    fee_rate = stats['fee_rate']
    exchange_rate = stats['exchange_rate']
    total_income_cny = stats['income_total']
    total_income_usdt = stats['income_usdt']
    total_expense_usdt = stats['expense_usdt']

    # 待下发 = 总入款USDT - 已下发USDT
    pending_usdt = total_income_usdt - total_expense_usdt

    message += f"💰 **费率**：{fee_rate}%\n"
    message += f"💱 **汇率**：{exchange_rate}\n\n"
    message += f"📊 **总入款**：{total_income_cny:.2f} = {total_income_usdt:.2f} USDT\n"
    message += f"📤 **已下发**：{total_expense_usdt:.2f} USDT\n"

    # 根据标题决定显示什么
    if title == "总计账单":
        message += f"📋 **总待出款**：{pending_usdt:.2f} USDT"
    else:
        message += f"⏳ **待下发**：{pending_usdt:.2f} USDT"

    return message

# --- 指令处理函数 ---

async def handle_end_bill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """结束当前账单"""
    chat = update.effective_chat
    user = update.effective_user

    if not is_authorized(user.id):
        await update.message.reply_text("❌ 此操作需要管理员权限")
        return

    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("❌ 此功能仅在群组中可用")
        return

    group_id = str(chat.id)

    stats = accounting_manager.get_current_stats(group_id)
    records = accounting_manager.get_current_records(group_id)

    if stats['income_count'] == 0 and stats['expense_count'] == 0:
        await update.message.reply_text("📭 当前没有账单记录，无需结束")
        return

    final_bill = format_bill_message(stats, records, "结束账单")

    result = accounting_manager.end_session(group_id)

    if result:
        await update.message.reply_text(
            f"✅ **账单已结束并保存！**\n\n{final_bill}\n\n"
            f"💡 提示：费率已重置为0%，汇率已重置为1 = 1 USDT\n"
            f"可使用「设置手续费」和「设置汇率」重新配置",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ 结束账单失败")


async def handle_set_fee(update: Update, context: ContextTypes.DEFAULT_TYPE, rate: float):
    """设置手续费率"""
    chat = update.effective_chat
    user = update.effective_user

    if not is_authorized(user.id):
        await update.message.reply_text("❌ 此操作需要管理员权限")
        return

    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("❌ 此功能仅在群组中可用")
        return

    group_id = str(chat.id)

    if accounting_manager.set_fee_rate(group_id, rate):
        stats = accounting_manager.get_current_stats(group_id)
        records = accounting_manager.get_current_records(group_id)
        message = format_bill_message(stats, records, "当前账单")
        await update.message.reply_text(
            f"✅ 手续费率已设置为 {rate}%\n\n{message}",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ 设置失败，请稍后重试")


async def handle_set_exchange(update: Update, context: ContextTypes.DEFAULT_TYPE, rate: float):
    """设置汇率"""
    chat = update.effective_chat
    user = update.effective_user

    if not is_authorized(user.id):
        await update.message.reply_text("❌ 此操作需要管理员权限")
        return

    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("❌ 此功能仅在群组中可用")
        return

    group_id = str(chat.id)

    if accounting_manager.set_exchange_rate(group_id, rate):
        stats = accounting_manager.get_current_stats(group_id)
        records = accounting_manager.get_current_records(group_id)
        message = format_bill_message(stats, records, "当前账单")
        await update.message.reply_text(
            f"✅ 汇率已设置为 {rate}\n\n{message}",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ 设置失败，请稍后重试")


async def handle_add_income(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: float, is_correction: bool = False):
    """添加入款记录（支持修正）"""
    chat = update.effective_chat
    user = update.effective_user

    if not is_authorized(user.id):
        await update.message.reply_text("❌ 此操作需要管理员权限")
        return

    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("❌ 此功能仅在群组中可用")
        return

    group_id = str(chat.id)
    username = user.username or user.first_name or str(user.id)

    # 如果是修正入款，金额为负数
    if is_correction:
        record_amount = -abs(amount)  # 负数，表示减少
        desc = "修正入款"
    else:
        record_amount = abs(amount)   # 正数，表示增加
        desc = "入款"

    # 添加记录时，amount 使用 record_amount（可以是负数）
    if accounting_manager.add_record(group_id, user.id, username, first_name, 'income', record_amount, desc):
        stats = accounting_manager.get_current_stats(group_id)
        records = accounting_manager.get_current_records(group_id)
        message = format_bill_message(stats, records, "当前账单")

        # 显示提示信息
        if is_correction:
            await update.message.reply_text(
                f"✅ 已记录修正入款：-{abs(amount):.2f} \n\n{message}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"✅ 已记录入款：{amount:.2f} \n\n{message}",
                parse_mode='Markdown'
            )
    else:
        await update.message.reply_text("❌ 记录失败，请稍后重试")


async def handle_add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: float, is_correction: bool = False):
    """添加出款记录（支持修正）"""
    chat = update.effective_chat
    user = update.effective_user

    if not is_authorized(user.id):
        await update.message.reply_text("❌ 此操作需要管理员权限")
        return

    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("❌ 此功能仅在群组中可用")
        return

    group_id = str(chat.id)
    username = user.username or user.first_name or str(user.id)

    # 如果是修正出款，金额为负数
    if is_correction:
        record_amount = -abs(amount)  # 负数，表示减少已下发
        desc = "修正出款"
    else:
        record_amount = abs(amount)   # 正数，表示增加已下发
        desc = "出款"

    # 添加记录时，amount 使用 record_amount（可以是负数）
    if accounting_manager.add_record(group_id, user.id, username, first_name, 'income', record_amount, desc):
        stats = accounting_manager.get_current_stats(group_id)
        records = accounting_manager.get_current_records(group_id)
        message = format_bill_message(stats, records, "当前账单")

        # 显示提示信息
        if is_correction:
            await update.message.reply_text(
                f"✅ 已记录修正出款：-{abs(amount):.2f} USDT\n\n{message}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"✅ 已记录出款：{amount:.2f} USDT\n\n{message}",
                parse_mode='Markdown'
            )
    else:
        await update.message.reply_text("❌ 记录失败，请稍后重试")


async def handle_total_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看总计账单"""
    chat = update.effective_chat

    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("❌ 此功能仅在群组中可用")
        return

    group_id = str(chat.id)
    stats = accounting_manager.get_total_stats(group_id)
    records = accounting_manager.get_total_records(group_id)

    if stats['income_count'] == 0 and stats['expense_count'] == 0:
        await update.message.reply_text("📭 暂无账单记录")
        return

    # 格式化总计账单
    message = f"📊 **总计账单**\n\n"

    # 分离入款和出款记录
    income_records = [r for r in records if r['type'] == 'income']
    expense_records = [r for r in records if r['type'] == 'expense']

    # 入款记录（显示最新的8条）
    if income_records:
        income_records_sorted = sorted(income_records, key=lambda x: x['created_at'], reverse=True)
        display_income = income_records_sorted[:8]
        total_income_count = len(income_records)

        message += f"📈 **入款 {total_income_count} 笔**"
        if total_income_count > 8:
            message += f" (显示最新8条)"
        message += "\n"

        for r in display_income:
            dt = beijing_time(r['created_at'])
            time_str = dt.strftime('%m-%d %H:%M')
            amount = r['amount']
            amount_usdt = r['amount_usdt']

            if amount < 0:
                message += f"`{time_str} {amount:.2f} = {amount_usdt:.2f} USDT`\n"
            else:
                message += f"`{time_str} +{amount:.2f} = {amount_usdt:.2f} USDT`\n"

        if total_income_count > 8:
            message += f"`... 还有 {total_income_count - 8} 条记录`\n"
        message += "\n"
    else:
        message += "📈 **入款 0 笔**\n\n"

    # 出款记录（显示最新的8条）
    if expense_records:
        expense_records_sorted = sorted(expense_records, key=lambda x: x['created_at'], reverse=True)
        display_expense = expense_records_sorted[:8]
        total_expense_count = len(expense_records)

        message += f"📉 **出款 {total_expense_count} 笔**"
        if total_expense_count > 8:
            message += f" (显示最新8条)"
        message += "\n"

        for r in display_expense:
            dt = beijing_time(r['created_at'])
            time_str = dt.strftime('%m-%d %H:%M')
            amount = r['amount']

            if amount < 0:
                message += f"`{time_str} {amount:.2f} USDT`\n"
            else:
                message += f"`{time_str} +{amount:.2f} USDT`\n"

        if total_expense_count > 8:
            message += f"`... 还有 {total_expense_count - 8} 条记录`\n"
        message += "\n"
    else:
        message += "📉 **出款 0 笔**\n\n"

    # 统计信息
    fee_rate = stats['fee_rate']
    exchange_rate = stats['exchange_rate']
    total_income_cny = stats['income_total']
    total_income_usdt = stats['income_usdt']
    total_expense_usdt = stats['expense_usdt']
    pending_usdt = total_income_usdt - total_expense_usdt

    message += f"💰 **费率**：{fee_rate}%\n"
    message += f"💱 **汇率**：{exchange_rate}\n\n"
    message += f"📊 **总入款**：{total_income_cny:.2f} = {total_income_usdt:.2f} USDT\n"
    message += f"📤 **已下发**：{total_expense_usdt:.2f} USDT\n"
    message += f"📋 **总待出款**：{pending_usdt:.2f} USDT"

    await update.message.reply_text(message, parse_mode='Markdown')


async def handle_today_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看今日账单"""
    chat = update.effective_chat

    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("❌ 此功能仅在群组中可用")
        return

    group_id = str(chat.id)
    stats = accounting_manager.get_today_stats(group_id)
    records = accounting_manager.get_today_records(group_id)

    if stats['income_count'] == 0 and stats['expense_count'] == 0:
        await update.message.reply_text("📭 今日暂无账单记录")
        return

    # 格式化今日账单（同样使用北京时间）
    message = f"📊 **今日账单**\n\n"

    # 分离入款和出款记录
    income_records = [r for r in records if r['type'] == 'income']
    expense_records = [r for r in records if r['type'] == 'expense']

    # 入款记录
    if income_records:
        income_records_sorted = sorted(income_records, key=lambda x: x['created_at'], reverse=True)
        display_income = income_records_sorted[:8]
        total_income_count = len(income_records)

        message += f"📈 **入款 {total_income_count} 笔**"
        if total_income_count > 8:
            message += f" (显示最新8条)"
        message += "\n"

        for r in display_income:
            dt = beijing_time(r['created_at'])
            time_str = dt.strftime('%H:%M')
            amount = r['amount']
            amount_usdt = r['amount_usdt']

            if amount < 0:
                message += f"`{time_str} {amount:.2f} = {amount_usdt:.2f} USDT`\n"
            else:
                message += f"`{time_str} +{amount:.2f} = {amount_usdt:.2f} USDT`\n"

        if total_income_count > 8:
            message += f"`... 还有 {total_income_count - 8} 条记录`\n"
        message += "\n"
    else:
        message += "📈 **入款 0 笔**\n\n"

    # 出款记录
    if expense_records:
        expense_records_sorted = sorted(expense_records, key=lambda x: x['created_at'], reverse=True)
        display_expense = expense_records_sorted[:8]
        total_expense_count = len(expense_records)

        message += f"📉 **出款 {total_expense_count} 笔**"
        if total_expense_count > 8:
            message += f" (显示最新8条)"
        message += "\n"

        for r in display_expense:
            dt = beijing_time(r['created_at'])
            time_str = dt.strftime('%H:%M')
            amount = r['amount']

            if amount < 0:
                message += f"`{time_str} {amount:.2f} USDT`\n"
            else:
                message += f"`{time_str} +{amount:.2f} USDT`\n"

        if total_expense_count > 8:
            message += f"`... 还有 {total_expense_count - 8} 条记录`\n"
        message += "\n"
    else:
        message += "📉 **出款 0 笔**\n\n"

    # 统计信息
    fee_rate = stats['fee_rate']
    exchange_rate = stats['exchange_rate']
    total_income_cny = stats['income_total']
    total_income_usdt = stats['income_usdt']
    total_expense_usdt = stats['expense_usdt']
    pending_usdt = stats['pending_usdt']

    message += f"💰 **费率**：{fee_rate}%\n"
    message += f"💱 **汇率**：{exchange_rate}\n\n"
    message += f"📊 **总入款**：{total_income_cny:.2f} = {total_income_usdt:.2f} USDT\n"
    message += f"📤 **已下发**：{total_expense_usdt:.2f} USDT\n"
    message += f"⏳ **待下发**：{pending_usdt:.2f} USDT"

    await update.message.reply_text(message, parse_mode='Markdown')


async def handle_current_bill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看当前账单"""
    chat = update.effective_chat

    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("❌ 此功能仅在群组中可用")
        return

    group_id = str(chat.id)
    stats = accounting_manager.get_current_stats(group_id)
    records = accounting_manager.get_current_records(group_id)

    if stats['income_count'] == 0 and stats['expense_count'] == 0:
        await update.message.reply_text(
            "📭 当前账单为空\n\n"
            "💡 使用以下指令开始记账：\n"
            "  • +金额 - 添加入款\n"
            "  • -金额 - 修正入款\n"
            "  • 下发金额u - 添加出款\n"
            "  • 下发-金额u - 修正出款\n"
            "  • 设置手续费 数字 - 设置手续费率\n"
            "  • 设置汇率 数字 - 设置汇率\n"
            "  • 结束账单 - 结束并保存当前账单"
        )
        return

    message = format_bill_message(stats, records, "当前账单")
    await update.message.reply_text(message, parse_mode='Markdown')


async def handle_query_bill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查询历史账单（按日期）"""
    chat = update.effective_chat

    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("❌ 此功能仅在群组中可用")
        return

    group_id = str(chat.id)
    dates = accounting_manager.get_sessions_by_date(group_id)

    if not dates:
        await update.message.reply_text("📭 暂无历史账单记录")
        return

    keyboard = []
    for date_info in dates[:10]:
        date_str = date_info['date']
        keyboard.append([InlineKeyboardButton(f"📅 {date_str}", callback_data=f"acct_date_{date_str}")])

    keyboard.append([InlineKeyboardButton("❌ 取消", callback_data="acct_cancel")])

    await update.message.reply_text(
        "📅 **请选择要查询的日期：**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return ACCOUNTING_DATE_SELECT


async def handle_date_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理日期选择"""
    query = update.callback_query
    await query.answer()

    date_str = query.data.replace("acct_date_", "")
    group_id = str(query.message.chat.id)

    stats = accounting_manager.get_stats_by_date(group_id, date_str)
    records = accounting_manager.get_records_by_date(group_id, date_str)

    if stats['income_count'] == 0 and stats['expense_count'] == 0:
        await query.message.edit_text(f"📭 {date_str} 暂无账单记录")
        return ConversationHandler.END

    message = f"📅 **{date_str} 账单**\n\n"

    # 分离入款和出款记录
    income_records = [r for r in records if r['type'] == 'income']
    expense_records = [r for r in records if r['type'] == 'expense']

    # 入款记录（只显示最新的8条，倒序显示）
    if income_records:
        income_records_sorted = sorted(income_records, key=lambda x: x['created_at'], reverse=True)
        display_income = income_records_sorted[:8]
        total_income_count = len(income_records)

        message += f"📈 **入款 {total_income_count} 笔**"
        if total_income_count > 8:
            message += f" (显示最新8条)"
        message += "\n"

        for r in display_income:
            dt = beijing_time(r['created_at'])
            time_str = dt.strftime('%H:%M')
            amount = r['amount']
            amount_usdt = r['amount_usdt']
            user_id = r['user_id']
            username = r['username']

            display_name = username if username else f"用户{user_id}"
            mention = f"[{display_name}](tg://user?id={user_id})"

            if amount < 0:
                message += f"`{time_str} {amount:.2f} = {amount_usdt:.2f} USDT`\n"
            else:
                message += f"`{time_str} +{amount:.2f} = {amount_usdt:.2f} USDT`\n"

        if total_income_count > 8:
            message += f"`... 还有 {total_income_count - 8} 条记录`\n"
        message += "\n"
    else:
        message += "📈 **入款 0 笔**\n\n"

    # 出款记录（只显示最新的8条，倒序显示）
    if expense_records:
        expense_records_sorted = sorted(expense_records, key=lambda x: x['created_at'], reverse=True)
        display_expense = expense_records_sorted[:8]
        total_expense_count = len(expense_records)

        message += f"📉 **出款 {total_expense_count} 笔**"
        if total_expense_count > 8:
            message += f" (显示最新8条)"
        message += "\n"

        for r in display_expense:  # ✅ 这里使用 display_expense
            dt = beijing_time(r['created_at'])
            time_str = dt.strftime('%H:%M')
            amount = r['amount']
            user_id = r['user_id']
            username = r['username']

            display_name = username if username else f"用户{user_id}"
            mention = f"[{display_name}](tg://user?id={user_id})"

            if amount < 0:
                message += f"`{time_str} {amount:.2f} USDT`\n"
            else:
                message += f"`{time_str} +{amount:.2f} USDT`\n"

        if total_expense_count > 8:
            message += f"`... 还有 {total_expense_count - 8} 条记录`\n"
        message += "\n"
    else:
        message += "📉 **出款 0 笔**\n\n"  # ✅ 当没有出款记录时，显示0笔

    total_income_cny = stats['income_total']
    total_income_usdt = stats['income_usdt']
    total_expense_usdt = stats['expense_usdt']
    pending_usdt = stats['pending_usdt']

    message += f"📊 **总入款**：{total_income_cny:.2f} = {total_income_usdt:.2f} USDT\n"
    message += f"📤 **已下发**：{total_expense_usdt:.2f} USDT\n"
    message += f"⏳ **待下发**：{pending_usdt:.2f} USDT"

    await query.message.edit_text(message, parse_mode='Markdown')
    return ConversationHandler.END


async def handle_clear_bill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """清空当前账单"""
    chat = update.effective_chat
    user = update.effective_user

    if not is_authorized(user.id):
        await update.message.reply_text("❌ 此操作需要管理员权限")
        return

    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("❌ 此功能仅在群组中可用")
        return

    group_id = str(chat.id)

    if accounting_manager.clear_current_session(group_id):
        await update.message.reply_text("✅ 已清空当前账单")
        stats = accounting_manager.get_current_stats(group_id)
        records = accounting_manager.get_current_records(group_id)
        message = format_bill_message(stats, records, "当前账单")
        await update.message.reply_text(message, parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ 清空失败，请稍后重试")


async def handle_calculator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理计算器功能"""
    chat = update.effective_chat

    if chat.type not in ['group', 'supergroup']:
        return

    text = update.message.text.strip()

    pattern = r'^(-?\d+(?:\.\d+)?)\s*([+\-*/])\s*(-?\d+(?:\.\d+)?)$'
    match = re.match(pattern, text)

    if not match:
        return

    a, op, b = match.groups()
    a_num = float(a)
    b_num = float(b)

    try:
        if op == '+':
            result = a_num + b_num
        elif op == '-':
            result = a_num - b_num
        elif op == '*':
            result = a_num * b_num
        elif op == '/':
            if b_num == 0:
                await update.message.reply_text("❌ 除数不能为0")
                return
            result = a_num / b_num
        else:
            return

        if result.is_integer():
            result_str = str(int(result))
        else:
            result_str = f"{result:.2f}"

        user_mention = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
        await update.message.reply_text(f"{user_mention} {a_num}{op}{b_num} = {result_str}")
    except Exception as e:
        print(f"计算错误: {e}")


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理群组消息中的记账指令"""
    chat = update.effective_chat
    message = update.message

    if not message or chat.type not in ['group', 'supergroup']:
        return

    text = message.text.strip() if message.text else ""

    # 【新增】追踪用户信息（所有人都会触发）
    await handle_user_info_tracking(update, context)
    
    if not text:
        return

    # 处理计算器功能（所有人可用）
    await handle_calculator(update, context)

    # 处理记账指令（需要权限）
    if not is_authorized(message.from_user.id):
        return

    # 设置手续费
    if text.startswith('设置手续费'):
        try:
            rate_str = text.replace('设置手续费', '').strip()
            if rate_str:
                rate = float(rate_str)
                await handle_set_fee(update, context, rate)
        except:
            await message.reply_text("❌ 格式错误：设置手续费 数字（如：设置手续费5）")

    # 设置汇率
    elif text.startswith('设置汇率'):
        try:
            rate_str = text.replace('设置汇率', '').strip()
            if rate_str:
                rate = float(rate_str)
                await handle_set_exchange(update, context, rate)
        except:
            await message.reply_text("❌ 格式错误：设置汇率 数字（如：设置汇率7.2）")

    # 结束账单
    elif text == '结束账单':
        await handle_end_bill(update, context)

    # 今日总
    elif text == '今日总':
        await handle_today_stats(update, context)

    # 总
    elif text == '总':
        await handle_total_stats(update, context)

    # 当前账单
    elif text == '当前账单':
        await handle_current_bill(update, context)

    # 查询账单
    elif text == '查询账单':
        await handle_query_bill(update, context)

    # 清理账单 / 清空账单
    elif text in ['清理账单', '清空账单']:
        await handle_clear_bill(update, context)

    # 清理总账单（所有账单）
    elif text in ['清理总账单', '清空总账单', '清空所有账单']:
        await handle_clear_all_bill(update, context)

    # +xxx 添加入款
    elif text.startswith('+'):
        try:
            amount_str = text[1:].strip()
            if amount_str:
                amount = float(amount_str)
                await handle_add_income(update, context, amount, is_correction=False)
            else:
                await message.reply_text("❌ 格式错误：+金额（如：+1000）")
        except:
            await message.reply_text("❌ 格式错误：+金额（如：+1000）")

    # -xxx 修正入款
    elif text.startswith('-') and len(text) > 1 and text[1:].replace('.', '').replace('-', '').replace('', '').isdigit():
        try:
            amount_str = text[1:].strip()
            if amount_str:
                amount = float(amount_str)
                await handle_add_income(update, context, amount, is_correction=True)
            else:
                await message.reply_text("❌ 格式错误：-金额（如：-500）")
        except:
            await message.reply_text("❌ 格式错误：-金额（如：-500）")

    # 下发 xxxu 添加出款（正数）
    elif text.startswith('下发') and 'u' in text and not text.startswith('下发-'):
        try:
            amount_str = text.replace('下发', '').replace('u', '').strip()
            if amount_str:
                amount = float(amount_str)
                await handle_add_expense(update, context, amount, is_correction=False)
            else:
                await message.reply_text("❌ 格式错误：下发金额u（如：下发100u）")
        except:
            await message.reply_text("❌ 格式错误：下发金额u（如：下发100u）")

    # 下发- xxxu 修正出款（负数）
    elif text.startswith('下发-') and 'u' in text:
        try:
            amount_str = text.replace('下发-', '').replace('u', '').strip()
            if amount_str:
                amount = float(amount_str)
                await handle_add_expense(update, context, amount, is_correction=True)
            else:
                await message.reply_text("❌ 格式错误：下发-金额u（如：下发-50u）")
        except:
            await message.reply_text("❌ 格式错误：下发-金额u（如：下发-50u）")

def get_conversation_handler():
    """获取记账模块的对话处理器"""
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_date_selection, pattern="^acct_date_"),
            CallbackQueryHandler(handle_clear_all_confirm, pattern="^clear_all_confirm$"),
            CallbackQueryHandler(handle_clear_all_cancel, pattern="^clear_all_cancel$"),
        ],
        states={
            ACCOUNTING_DATE_SELECT: [
                CallbackQueryHandler(handle_date_selection, pattern="^acct_date_"),
                CallbackQueryHandler(lambda u, c: ConversationHandler.END, pattern="^acct_cancel$"),
            ],
            ACCOUNTING_CONFIRM_CLEAR: [
                CallbackQueryHandler(handle_clear_confirm, pattern="^acct_clear_confirm$"),
                CallbackQueryHandler(handle_clear_cancel, pattern="^acct_clear_cancel$"),
            ],
            ACCOUNTING_CONFIRM_CLEAR_ALL: [
                CallbackQueryHandler(handle_clear_all_confirm, pattern="^clear_all_confirm$"),
                CallbackQueryHandler(handle_clear_all_cancel, pattern="^clear_all_cancel$"),
            ],
        },
        fallbacks=[],
        per_message=False,
    )
    return conv_handler

async def handle_clear_all_bill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """清空所有账单（包括历史记录）"""
    chat = update.effective_chat
    user = update.effective_user

    if not is_authorized(user.id):
        await update.message.reply_text("❌ 此操作需要管理员权限")
        return

    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("❌ 此功能仅在群组中可用")
        return

    group_id = str(chat.id)

    # 获取当前账单统计，用于确认
    stats = accounting_manager.get_current_stats(group_id)
    total_stats = accounting_manager.get_total_stats(group_id)

    if total_stats['income_count'] == 0 and total_stats['expense_count'] == 0:
        await update.message.reply_text("📭 暂无任何账单记录")
        return

    # 创建确认按钮
    keyboard = [
        [InlineKeyboardButton("✅ 确认清空所有账单", callback_data="clear_all_confirm")],
        [InlineKeyboardButton("❌ 取消", callback_data="clear_all_cancel")]
    ]

    await update.message.reply_text(
        f"⚠️ **警告：此操作将清空本群的所有账单记录！**\n\n"
        f"📊 当前统计：\n"
        f"  总入款：{total_stats['income_total']:.2f} CNY = {total_stats['income_usdt']:.2f} USDT\n"
        f"  总下发：{total_stats['expense_usdt']:.2f} USDT\n"
        f"  记录总数：{total_stats['income_count'] + total_stats['expense_count']} 笔\n\n"
        f"确认要继续吗？此操作不可恢复！",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return ACCOUNTING_CONFIRM_CLEAR

async def handle_clear_all_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """确认清空所有账单"""
    query = update.callback_query
    await query.answer()

    group_id = str(query.message.chat.id)

    if accounting_manager.clear_all_records(group_id):
        await query.message.edit_text("✅ 已清空本群所有账单记录（包括历史记录）")

        # 显示空账单
        stats = accounting_manager.get_current_stats(group_id)
        records = accounting_manager.get_current_records(group_id)
        message = format_bill_message(stats, records, "当前账单")
        await query.message.reply_text(message, parse_mode='Markdown')
    else:
        await query.message.edit_text("❌ 清空失败，请稍后重试")

    return ConversationHandler.END


async def handle_clear_all_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消清空所有账单"""
    query = update.callback_query
    await query.answer()

    await query.message.edit_text("✅ 已取消清空操作")
    return ConversationHandler.END

# 用户信息追踪功能
async def handle_user_info_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """追踪用户信息变更"""
    chat = update.effective_chat
    user = update.effective_user

    if not user or chat.type not in ['group', 'supergroup']:
        return

    group_id = str(chat.id)
    username = user.username
    first_name = user.first_name
    last_name = user.last_name or ""

    has_change, old_name, new_name, change_type = accounting_manager.update_user_info(
        group_id, user.id, username, first_name, last_name
    )

    if has_change:
        if change_type:
            await update.message.reply_text(
                f"🚨 **用户信息变更提醒**\n\n"
                f"用户 {old_name}\n"
                f"已更新{change_type}为：\n"
                f"{new_name}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"🚨 **用户信息变更提醒**\n\n"
                f"用户 {old_name} → {new_name}",
                parse_mode='Markdown'
            )


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理记账菜单按钮点击"""
    query = update.callback_query
    await query.answer()

    if not is_authorized(query.from_user.id):
        await query.message.reply_text("❌ 此功能仅限管理员或操作员使用")
        return

    message = (
        "📒 **记账功能说明**\n\n"
        "💰 **入款操作**：\n"
        "`+金额` - 添加一笔入款（如：+1000）\n"
        "`-金额` - 修正入款（如：-500）\n\n"
        "💸 **出款操作**：\n"
        "`下发金额u` - 添加出款（如：下发100u）\n"
        "`下发-金额u` - 修正出款（如：下发-50u）\n\n"
        "⚙️ **配置**：\n"
        "`设置手续费 数字` - 设置手续费率（如：设置手续费 5）\n"
        "`设置汇率 数字` - 设置汇率（如：设置汇率 7.2）\n\n"
        "📊 **查询**：\n"
        "`今日总` - 查看今日账单\n"
        "`总` - 查看总计账单\n"
        "`查询账单` - 按日期查询\n"
        "`当前账单` - 查看当前账单\n\n"
        "🗑️ **管理**：\n"
        "`结束账单` - 结束并保存当前账单（费率/汇率重置）\n"
        "`清理账单` - 清空当前账单\n\n"
        "`清理总账单` - 清空所有账单（包括历史记录）\n\n"
        "🧮 **计算器**：\n"
        "`数字+数字`、`数字-数字`、`数字*数字`、`数字/数字`\n\n"
        "⚠️ 注意：所有记账操作需要管理员或操作员权限"
    )

    await query.message.reply_text(message, parse_mode='Markdown')
