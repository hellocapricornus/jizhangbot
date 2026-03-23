# handlers/menu.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("📒 记账", callback_data="accounting")],
        [InlineKeyboardButton("📢 群发", callback_data="broadcast")],
        [InlineKeyboardButton("💰 USDT地址查询", callback_data="usdt")],
        [InlineKeyboardButton("👤 操作人管理", callback_data="operator")],
        [InlineKeyboardButton("🔄 互转查询", callback_data="transfer")],
        [InlineKeyboardButton("📁 群组管理", callback_data="group_manager")],  # 新增这个按钮
    ]
    return InlineKeyboardMarkup(keyboard)
