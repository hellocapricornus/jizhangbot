# handlers/start.py - 删除 handle_private_message 函数

from telegram import Update
from telegram.ext import ContextTypes
from auth import is_authorized
from handlers.menu import get_main_menu

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /start 命令"""
    user_id = update.effective_user.id
    chat = update.effective_chat

    # 群组中的处理
    if chat.type in ['group', 'supergroup']:
        await update.message.reply_text(
            "🤖 机器人已启动\n\n"
            "📊 **群组功能**：\n"
            "• 记账：+金额、-金额、下发金额u\n"
            "• 计算器：100+200\n"
            "• 统计：今日总、总\n"
            "• AI 对话：@我 然后提问\n\n"
            "🔧 **管理功能**请私聊机器人使用 /start"
        )
        return

    # 私聊中的处理 - 显示菜单
    await update.message.reply_text(
        "请选择功能：",
        reply_markup=get_main_menu()
    )

# ✅ 删除下面的整个 handle_private_message 函数
# async def handle_private_message(...):
#     ...
