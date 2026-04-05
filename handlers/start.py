# handlers/start.py

from telegram import Update
from telegram.ext import ContextTypes
from auth import is_authorized
from handlers.menu import get_main_menu
from handlers.ai_client import get_ai_client

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


async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理私聊消息（包括 AI 对话）"""
    chat = update.effective_chat
    message = update.message

    if not message or chat.type != 'private':
        return

    text = message.text.strip() if message.text else ""

    if not text:
        return

    # 如果是命令，交给其他处理器
    if text.startswith('/'):
        return

    # ✅ 添加权限检查
    from auth import is_authorized
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await message.reply_text(
            "❌ AI 对话功能仅限管理员和操作员使用\n\n"
            "如需使用，请联系 @ChinaEdward 申请权限"
        )
        return

    # 普通文本消息，调用 AI 回复
    thinking_msg = await message.reply_text("🤔 思考中...")

    ai_client = get_ai_client()
    reply = await ai_client.chat(text)

    if len(reply) > 4000:
        reply = reply[:4000] + "...\n\n(回复过长已截断)"

    await thinking_msg.edit_text(reply)
