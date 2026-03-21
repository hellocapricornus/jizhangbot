from telegram import Update
from telegram.ext import ContextTypes
from handlers.menu import get_main_menu

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "请选择功能：",
        reply_markup=get_main_menu()
    )
