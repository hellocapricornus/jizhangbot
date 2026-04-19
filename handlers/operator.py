# handlers/operator.py

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from auth import (
    add_operator, remove_operator, get_operators_list_text, 
    cmd_update_operator_info, update_all_operators_info,
    add_temp_operator, remove_temp_operator, get_temp_operators_list_text
)
from config import OWNER_ID

# 状态标识
ADD_OPERATOR = 1
REMOVE_OPERATOR = 2
ADD_TEMP_OPERATOR = 3
REMOVE_TEMP_OPERATOR = 4

# 点击操作人按钮
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if user_id != OWNER_ID:
        await query.answer("❌ 只有控制人可以管理操作人", show_alert=True)
        await query.message.reply_text("❌ 只有控制人可以管理操作人")
        return

    # 清除之前可能残留的状态
    context.user_data.pop("active_module", None)
    context.user_data.pop("current_action", None)

    keyboard = [
        [InlineKeyboardButton("➕ 添加操作人", callback_data="op_add")],
        [InlineKeyboardButton("➖ 删除操作人", callback_data="op_remove")],
        [InlineKeyboardButton("📋 查询操作人", callback_data="op_list")],
        [InlineKeyboardButton("🔄 更新信息", callback_data="op_update")],
        [InlineKeyboardButton("👥 临时操作人", callback_data="op_temp_menu")],
        [InlineKeyboardButton("◀️ 返回主菜单", callback_data="main_menu")],
    ]
    await query.message.reply_text(
        "👤 操作人管理：请选择功能",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# 新增：临时操作人子菜单
async def temp_operator_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """临时操作人管理菜单"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("➕ 添加临时操作人", callback_data="op_temp_add")],
        [InlineKeyboardButton("➖ 删除临时操作人", callback_data="op_temp_remove")],
        [InlineKeyboardButton("📋 查询临时操作人", callback_data="op_temp_list")],
        [InlineKeyboardButton("◀️ 返回", callback_data="operator")],
    ]

    await query.message.edit_text(
        "👥 **临时操作人管理**\n\n"
        "临时操作人**只能使用记账功能**，不能使用：\n"
        "❌ USDT查询\n"
        "❌ 群发消息\n"
        "❌ 互转查询\n"
        "❌ 群组管理\n"
        "❌ 操作人管理\n\n"
        "✅ 只能使用：记账、地址查询、计算器\n\n"
        "请选择操作：",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )  # ✅ 这里添加了右括号

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
        context.user_data["active_module"] = "operator"
        await query.message.reply_text("请输入要添加的用户ID（纯数字）：")

    elif data == "op_remove":
        context.user_data["current_action"] = REMOVE_OPERATOR
        context.user_data["active_module"] = "operator"
        await query.message.reply_text("请输入要删除的用户ID（纯数字）：")

    elif data == "op_list":
        # 使用新的函数生成格式化的文本（会同时显示正式和临时操作人）
        text = get_operators_list_text()
        await query.message.reply_text(text, parse_mode="Markdown")
        context.user_data.pop("active_module", None)

    elif data == "op_update":
        await query.message.reply_text("🔄 正在更新操作人信息，请稍候...")
        count = await update_all_operators_info(context)
        if count > 0:
            await query.message.reply_text(f"✅ 已成功更新 {count} 个操作人的信息")
            text = get_operators_list_text()
            await query.message.reply_text(text, parse_mode="Markdown")
        else:
            await query.message.reply_text("⚠️ 没有操作人被更新，或更新失败")

    # ========== 临时操作人处理 ==========
    elif data == "op_temp_menu":
        await temp_operator_menu(update, context)

    elif data == "op_temp_add":
        context.user_data["current_action"] = ADD_TEMP_OPERATOR
        context.user_data["active_module"] = "operator"
        await query.message.reply_text("请输入要添加的**临时操作人**ID（纯数字）：\n\n💡 临时操作人只能使用记账功能")

    elif data == "op_temp_remove":
        context.user_data["current_action"] = REMOVE_TEMP_OPERATOR
        context.user_data["active_module"] = "operator"
        await query.message.reply_text("请输入要删除的**临时操作人**ID（纯数字）：")

    elif data == "op_temp_list":
        text = get_temp_operators_list_text()
        await query.message.reply_text(text, parse_mode="Markdown")
        context.user_data.pop("active_module", None)

# 输入处理
async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    action = context.user_data.get("current_action")

    if action not in [ADD_OPERATOR, REMOVE_OPERATOR, ADD_TEMP_OPERATOR, REMOVE_TEMP_OPERATOR]:
        return
    if user_id != OWNER_ID:
        return

    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ 请输入正确的用户ID（纯数字）")
        return

    target_id = int(text)

    if action == ADD_OPERATOR:
        success = await add_operator(target_id, context)
        if success:
            from auth import get_operator_info
            info = get_operator_info(target_id)
            if info and info.get('first_name'):
                display = f"{info['first_name']}"
                if info.get('username'):
                    display += f" (@{info['username']})"
                await update.message.reply_text(f"✅ 已添加操作人：{display}")
            else:
                await update.message.reply_text(f"✅ 已添加操作人ID：{target_id}")
        else:
            await update.message.reply_text(f"❌ 添加失败，操作人可能已存在")

    elif action == REMOVE_OPERATOR:
        if remove_operator(target_id):
            await update.message.reply_text(f"✅ 已删除操作人：{target_id}")
        else:
            await update.message.reply_text(f"❌ 未找到操作人：{target_id}")

    elif action == ADD_TEMP_OPERATOR:
        # 检查是否已经是正式操作人
        from auth import operators
        if target_id in operators:
            await update.message.reply_text(
                f"❌ 添加失败：用户 {target_id} 已经是正式操作人\n\n"
                f"💡 正式操作人拥有完整权限，无需添加为临时操作人"
            )
        else:
            success = await add_temp_operator(target_id, user_id, context)
            if success:
                await update.message.reply_text(
                    f"✅ 已添加临时操作人：{target_id}\n\n"
                    f"⚠️ 该用户只能使用记账功能\n"
                    f"（记账、地址查询、计算器）"
                )
            else:
                await update.message.reply_text(f"❌ 添加失败，临时操作人可能已存在")

    elif action == REMOVE_TEMP_OPERATOR:
        if remove_temp_operator(target_id):
            await update.message.reply_text(f"✅ 已删除临时操作人：{target_id}")
        else:
            await update.message.reply_text(f"❌ 未找到临时操作人：{target_id}")

    # 清除状态
    context.user_data.pop("current_action", None)
    context.user_data.pop("active_module", None)

    # 显示操作人管理菜单
    keyboard = [
        [InlineKeyboardButton("➕ 添加操作人", callback_data="op_add")],
        [InlineKeyboardButton("➖ 删除操作人", callback_data="op_remove")],
        [InlineKeyboardButton("📋 查询操作人", callback_data="op_list")],
        [InlineKeyboardButton("🔄 更新信息", callback_data="op_update")],
        [InlineKeyboardButton("👥 临时操作人", callback_data="op_temp_menu")],
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

    keyboard = [
        [InlineKeyboardButton("➕ 添加操作人", callback_data="op_add")],
        [InlineKeyboardButton("➖ 删除操作人", callback_data="op_remove")],
        [InlineKeyboardButton("📋 查询操作人", callback_data="op_list")],
        [InlineKeyboardButton("🔄 更新信息", callback_data="op_update")],
        [InlineKeyboardButton("👥 临时操作人", callback_data="op_temp_menu")],
        [InlineKeyboardButton("◀️ 返回主菜单", callback_data="main_menu")],
    ]
    await update.message.reply_text(
        "👤 操作人管理：请选择功能",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END
