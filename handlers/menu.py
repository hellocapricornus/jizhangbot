# handlers/menu.py
from telegram import ReplyKeyboardMarkup, KeyboardButton
from auth import is_authorized

def get_main_menu(user_id: int):
    """
    根据用户权限返回不同的主菜单键盘
    - 完整权限（控制人 / 正式操作员）：全部功能按钮
    - 临时操作员 / 普通用户：仅显示 记账、使用说明、个人中心
    """
    if is_authorized(user_id, require_full_access=True):
        # 完整权限：原来的9个按钮
        keyboard = [
            [KeyboardButton("📒 记账"), KeyboardButton("🔔 USDT监控"), KeyboardButton("📢 群发")],
            [KeyboardButton("💰 USDT查询"), KeyboardButton("👤 操作人管理"), KeyboardButton("🔄 互转查询")],
            [KeyboardButton("📁 群组管理"), KeyboardButton("📖 使用说明"), KeyboardButton("👤 个人中心")],
        ]
    else:
        # 受限权限：仅3个按钮
        keyboard = [
            [KeyboardButton("📒 记账"), KeyboardButton("📖 使用说明"), KeyboardButton("👤 个人中心")],
        ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
