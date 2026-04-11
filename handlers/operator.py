from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from auth import add_operator, remove_operator, list_operators
from config import OWNER_ID

# 状态标识
ADD_OPERATOR = "operator_add"
REMOVE_OPERATOR = "operator_remove"

# 点击操作人按钮
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if user_id != OWNER_ID:
        await query.message.reply_text("❌ 只有控制人可以管理操作人")
        return

    # ✅ 清除之前可能残留的状态
    context.user_data.pop("active_module", None)
    context.user_data.pop("current_action", None)

    keyboard = [
        [InlineKeyboardButton("➕ 添加操作人", callback_data="op_add")],
        [InlineKeyboardButton("➖ 删除操作人", callback_data="op_remove")],
        [InlineKeyboardButton("📋 查询操作人", callback_data="op_list")],
        [InlineKeyboardButton("◀️ 返回主菜单", callback_data="main_menu")],  # 新增
    ]
    await query.message.reply_text(
        "👤 操作人管理：请选择功能",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# 子按钮处理
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if user_id != OWNER_ID:
        await query.message.reply_text("❌ 无权限")
        return

    data = query.data

    if data == "op_add":
        context.user_data["current_action"] = ADD_OPERATOR
        context.user_data["active_module"] = "operator"  # 设置模块
        await query.message.reply_text("请输入要添加的用户ID（纯数字）：")
    elif data == "op_remove":
        context.user_data["current_action"] = REMOVE_OPERATOR
        context.user_data["active_module"] = "operator"  # 设置模块
        await query.message.reply_text("请输入要删除的用户ID（纯数字）：")
    elif data == "op_list":
        ops = list_operators()
        if not ops:
            await query.message.reply_text("📭 当前没有操作人")
        else:
            text = "📋 操作人列表：\n" + "\n".join([str(i) for i in ops])
            await query.message.reply_text(text)

        # 操作完成后清除模块状态
        context.user_data.pop("active_module", None)

# 输入处理
async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    action = context.user_data.get("current_action")
    if action not in [ADD_OPERATOR, REMOVE_OPERATOR]:
        return
    if user_id != OWNER_ID:
        return

    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ 请输入正确的用户ID（纯数字）")
        return

    target_id = int(text)
    if action == ADD_OPERATOR:
        add_operator(target_id)
        await update.message.reply_text(f"✅ 已添加操作人：{target_id}")
    elif action == REMOVE_OPERATOR:
        remove_operator(target_id)
        await update.message.reply_text(f"✅ 已删除操作人：{target_id}")

    context.user_data.pop("current_action", None)
    context.user_data.pop("active_module", None)
    # ✅ 操作完成后显示操作人管理菜单（带返回按钮）
    keyboard = [
        [InlineKeyboardButton("➕ 添加操作人", callback_data="op_add")],
        [InlineKeyboardButton("➖ 删除操作人", callback_data="op_remove")],
        [InlineKeyboardButton("📋 查询操作人", callback_data="op_list")],
        [InlineKeyboardButton("◀️ 返回主菜单", callback_data="main_menu")],
    ]
    await update.message.reply_text(
        "👤 操作人管理：请选择功能",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def cancel_operator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消操作员管理"""
    context.user_data.pop("current_action", None)
    context.user_data.pop("active_module", None)
    await update.message.reply_text("❌ 已取消操作")
    # ✅ 取消后也显示操作人管理菜单
    keyboard = [
        [InlineKeyboardButton("➕ 添加操作人", callback_data="op_add")],
        [InlineKeyboardButton("➖ 删除操作人", callback_data="op_remove")],
        [InlineKeyboardButton("📋 查询操作人", callback_data="op_list")],
        [InlineKeyboardButton("◀️ 返回主菜单", callback_data="main_menu")],
    ]
    await update.message.reply_text(
        "👤 操作人管理：请选择功能",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END
