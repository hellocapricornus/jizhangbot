# db_manager.py
"""
多数据库连接管理器
- master.db: 存储管理员、操作员归属等全局信息
- data/admin_{admin_id}.db: 每个管理员独立的业务数据库
"""
import sqlite3
import os
import time
from typing import Dict, Optional
from logger import bot_logger as logger

# 连接缓存: key = admin_id (0 表示主库)
_connections: Dict[int, sqlite3.Connection] = {}

# 数据库文件路径
MASTER_DB_PATH = "master.db"
DATA_DIR = "data"          # 存放独立数据库的目录


def _ensure_data_dir():
    """确保数据目录存在"""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)


def get_conn(admin_id: int) -> sqlite3.Connection:
    """
    获取指定管理员的数据库连接
    - admin_id == 0: 返回主库连接 (master.db)
    - admin_id > 0: 返回该管理员的独立数据库连接
    """
    if admin_id in _connections:
        return _connections[admin_id]

    if admin_id == 0:
        db_path = MASTER_DB_PATH
    else:
        _ensure_data_dir()
        db_path = os.path.join(DATA_DIR, f"admin_{admin_id}.db")

    # 创建连接 (允许跨线程使用，因为 asyncio 中每个任务可能在多个线程)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _connections[admin_id] = conn
    return conn


def close_all_connections():
    """关闭所有数据库连接（程序退出时调用）"""
    for conn in _connections.values():
        conn.close()
    _connections.clear()


# ==================== 独立数据库初始化 ====================
def init_admin_db(admin_id: int):
    """
    初始化一个管理员的独立数据库（如果已存在则跳过）
    注意：此函数不会自动创建 master.db 中的管理员记录，只创建物理文件
    """
    db_path = os.path.join(DATA_DIR, f"admin_{admin_id}.db")
    if os.path.exists(db_path):
        return

    _ensure_data_dir()
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        -- 群组表
        CREATE TABLE IF NOT EXISTS groups (
            group_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            last_seen INTEGER DEFAULT 0,
            category TEXT DEFAULT '未分类',
            joined_at INTEGER DEFAULT 0,
            admin_id INTEGER DEFAULT 0
        );

        -- 分类表
        CREATE TABLE IF NOT EXISTS group_categories (
            category_id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_name TEXT UNIQUE NOT NULL,
            created_at INTEGER DEFAULT 0,
            description TEXT
        );

        -- 群组记账配置表
        CREATE TABLE IF NOT EXISTS group_accounting_config (
            group_id TEXT PRIMARY KEY,
            fee_rate REAL DEFAULT 0.0,
            exchange_rate REAL DEFAULT 1.0,
            per_transaction_fee REAL DEFAULT 0.0,
            session_id TEXT,
            session_start_time INTEGER DEFAULT 0,
            session_end_time INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            updated_at INTEGER DEFAULT 0
        );

        -- 监控地址表
        CREATE TABLE IF NOT EXISTS monitored_addresses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT NOT NULL,
            chain_type TEXT NOT NULL,
            added_by INTEGER NOT NULL,
            added_at INTEGER NOT NULL,
            last_check INTEGER DEFAULT 0,
            last_tx_id TEXT,
            note TEXT DEFAULT ''
        );

        -- 地址交易记录表
        CREATE TABLE IF NOT EXISTS address_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT NOT NULL,
            tx_id TEXT NOT NULL,
            from_addr TEXT,
            to_addr TEXT,
            amount REAL,
            timestamp INTEGER NOT NULL,
            notified INTEGER DEFAULT 0
        );

        -- 记账记录表
        CREATE TABLE IF NOT EXISTS accounting_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT,
            record_type TEXT NOT NULL,
            amount REAL NOT NULL,
            amount_usdt REAL NOT NULL,
            description TEXT,
            category TEXT DEFAULT '',
            rate REAL DEFAULT 0,
            fee_rate REAL DEFAULT 0,
            per_transaction_fee REAL DEFAULT 0,
            message_id INTEGER DEFAULT 0,
            created_at INTEGER NOT NULL,
            date TEXT NOT NULL,
            admin_id INTEGER DEFAULT 0
        );

        -- 历史会话表
        CREATE TABLE IF NOT EXISTS accounting_sessions (
            session_id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL,
            start_time INTEGER NOT NULL,
            end_time INTEGER NOT NULL,
            date TEXT NOT NULL,
            fee_rate REAL DEFAULT 0.0,
            exchange_rate REAL DEFAULT 1.0,
            per_transaction_fee REAL DEFAULT 0.0
        );

        -- 群组用户表（用于显示操作人昵称等）
        CREATE TABLE IF NOT EXISTS group_users (
            group_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            last_seen INTEGER NOT NULL,
            PRIMARY KEY (group_id, user_id)
        );

        -- 地址查询记录表（用于统计查询次数）
        CREATE TABLE IF NOT EXISTS address_queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id TEXT NOT NULL,
            address TEXT NOT NULL,
            chain_type TEXT NOT NULL,
            query_time INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT,
            balance REAL,
            UNIQUE(group_id, address)
        );

        CREATE TABLE IF NOT EXISTS address_query_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT NOT NULL,
            query_time INTEGER NOT NULL,
            balance REAL
        );

        -- 用户偏好表（每个管理员的用户偏好独立）
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id INTEGER PRIMARY KEY,
            monitor_notify INTEGER DEFAULT 1,
            broadcast_signature TEXT DEFAULT '',
            daily_report_enabled INTEGER DEFAULT 0,
            daily_report_hour INTEGER DEFAULT 9,
            role TEXT DEFAULT 'user',
            updated_at INTEGER DEFAULT 0
        );

        -- 索引
        CREATE INDEX IF NOT EXISTS idx_records_group_id ON accounting_records(group_id);
        CREATE INDEX IF NOT EXISTS idx_records_session_id ON accounting_records(session_id);
        CREATE INDEX IF NOT EXISTS idx_records_date ON accounting_records(date);
        CREATE INDEX IF NOT EXISTS idx_records_group_date ON accounting_records(group_id, date);
        CREATE INDEX IF NOT EXISTS idx_records_created ON accounting_records(created_at);
        CREATE INDEX IF NOT EXISTS idx_groups_category ON groups(category);
        CREATE INDEX IF NOT EXISTS idx_groups_last_seen ON groups(last_seen);
        CREATE INDEX IF NOT EXISTS idx_users_group_id ON group_users(group_id);
    """)

    # 插入默认分类“未分类”
    now = int(time.time())
    conn.execute("INSERT OR IGNORE INTO group_categories (category_name, created_at) VALUES ('未分类', ?)", (now,))
    conn.commit()
    conn.close()
    logger.info(f"已创建管理员 {admin_id} 的独立数据库: {db_path}")


# ==================== 主数据库初始化 ====================
def init_master_db():
    """初始化主数据库（存储全局管理员、操作员归属等）"""
    conn = get_conn(0)   # admin_id=0 表示主库
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS admins (
            admin_id INTEGER PRIMARY KEY,
            added_by INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            deleted_at INTEGER DEFAULT 0,
            db_path TEXT
        );

        CREATE TABLE IF NOT EXISTS operators (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            added_by INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS temp_operators (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            added_at INTEGER,
            added_by INTEGER
        );

        -- 用户所属管理员快速查找表（可选，用于加速）
        CREATE TABLE IF NOT EXISTS user_admin_mapping (
            user_id INTEGER PRIMARY KEY,
            admin_id INTEGER NOT NULL
        );
    """)
    conn.commit()
    logger.info("主数据库初始化完成")
