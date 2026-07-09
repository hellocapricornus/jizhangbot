# handlers/profile.py

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from handlers.menu import get_main_menu
from auth import is_authorized, OWNER_ID, safe_escape_markdown
from db import get_monitored_addresses, get_user_preferences, set_user_preference, \
    get_employee_response_stats, get_employee_work_time, get_response_rating_for_seconds

# 状态定义
PROFILE_MAIN = 1
SET_SIGNATURE = 2
EXPORT_DATA = 4
# ========== 规则管理状态 ==========
RULE_MENU = 5
RULE_ADD_NAME = 6
RULE_ADD_CONTENT = 7
RULE_UPDATE_SELECT = 8
RULE_UPDATE_CONTENT = 9
RULE_DELETE_SELECT = 10
RULE_TOGGLE_SELECT = 11
RULE_VIEW = 12

# ========== 业绩汇总状态 ==========
PERFORMANCE_MENU = 17
PERFORMANCE_RECORD = 18
PERFORMANCE_VIEW = 19
PERFORMANCE_MONTH_SELECT = 20
PERFORMANCE_EDIT = 21
PERFORMANCE_DELETE = 22

# ========== 亏损记录状态 ==========
LOSS_RECORD = 23
LOSS_EDIT = 24
LOSS_DELETE = 25

# ========== 比例设置状态 ==========
PERFORMANCE_SETTINGS = 26

def _is_keyboard_button(text: str) -> bool:
    """检查是否是键盘按钮"""
    keyboard_buttons = {
        "◀️ 返回主菜单", "📒 记账", "🔔 USDT监控", "📢 群发", "💰 USDT查询",
        "👤 操作人管理", "🔄 互转查询", "📁 群组管理", "📖 使用说明", "👤 个人中心",
        "➕ 添加操作人", "➖ 删除操作人", "📋 操作人列表", "🔄 更新操作人信息", "👥 临时操作人",
        "➕ 添加临时操作人", "➖ 删除临时操作人", "📋 临时操作人列表", "◀️ 返回操作人管理",
        "➕ 添加监控地址", "📋 监控列表", "📊 月度统计", "❌ 删除监控地址",
        "📊 群组统计", "📁 查看分类", "➕ 创建分类", "🏷️ 设置群组分类", "🗑️ 删除分类",
        "🔍 转账查询", "🕸️ 转账分析",
    }
    return text in keyboard_buttons

# ---------- 辅助：构建个人中心菜单 ----------
async def _build_profile_menu(user_id: int, prefs: dict = None, display_name: str = "") -> tuple:
    """返回 (消息文本, InlineKeyboardMarkup)"""
    if prefs is None:
        prefs = get_user_preferences(user_id)

    full_access = is_authorized(user_id, require_full_access=True)
    limited_access = is_authorized(user_id, require_full_access=False) and not full_access  # 临时操作员
    # 普通用户: not is_authorized at all

    # 获取监控地址数量
    addresses = get_monitored_addresses(user_id=user_id)

    # 身份文本
    if user_id == OWNER_ID:
        role = "👑 控制人"
    elif full_access:
        role = "👤 正式操作员"
    elif limited_access:
        role = "👥 临时操作员"
    else:
        role = "🙍 普通用户"

    keyboard = []

    # 监控交易提醒：仅完整权限且添加了监控地址时显示
    if full_access and addresses:
        notify = "🟢 已开启" if prefs["monitor_notify"] else "🔴 已关闭"
        keyboard.append([InlineKeyboardButton(f"🔔 监控交易提醒：{notify}", callback_data="profile_toggle_notify")])

    # 默认群发附言：仅完整权限
    if full_access:
        keyboard.append([InlineKeyboardButton("📝 默认群发附言", callback_data="profile_signature")])

    # ========== 规则管理（仅完整权限可见） ==========
    if full_access:
        from db import get_all_rules
        rules = get_all_rules(active_only=True)
        rule_count = len(rules)
        keyboard.append([InlineKeyboardButton(f"📋 规则管理（{rule_count}个）", callback_data="profile_rules_menu")])

    # ========== 业绩汇总（所有有权限的人可见） ==========
    if full_access:
        keyboard.append([InlineKeyboardButton("📊 业绩汇总", callback_data="profile_performance_menu")])

    # ========== 响应速度（所有有权限的人可见） ==========
    if is_authorized(user_id):
        keyboard.append([InlineKeyboardButton("⚡ 员工响应速度", callback_data="response_speed_menu")])

    # ========== 员工管理（超级管理员）/ 我的任务（员工） ==========
    if user_id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("👤 员工管理", callback_data="employee_menu")])
    elif is_authorized(user_id):
        keyboard.append([InlineKeyboardButton("📋 我的任务", callback_data="employee_my_tasks")])

    keyboard.append([InlineKeyboardButton("◀️ 返回主菜单", callback_data="profile_back")])

    # 构建提示文本
    if full_access and addresses:
        notify_status = f"📢 监控交易提醒：{'🟢 已开启' if prefs['monitor_notify'] else '🔴 已关闭'}\n"
    else:
        notify_status = ""
    user_info_line = f"👤 用户名：{display_name}\n" if display_name else ""

    response_info = ""
    if is_authorized(user_id):
        now = datetime.now(timezone(timedelta(hours=8)))
        response_stats = get_employee_response_stats(user_id, now.year, now.month)
        if response_stats['total_count'] > 0:
            avg_time = response_stats['avg_response_seconds']
            rating = get_response_rating_for_seconds(avg_time)
            response_info = f"⚡ 本月响应速度：{int(avg_time // 60)}分{int(avg_time % 60)}秒 {rating['emoji']}\n"

        work_time = get_employee_work_time(user_id)
        if work_time:
            response_info += f"⏰ 工作时间：{work_time['work_start']}-{work_time['work_end']}\n"

    text = (f"👤 个人中心\n\n"
            f"{user_info_line}"
            f"🆔 用户 ID：`{user_id}`\n"
            f"🏷️ 当前身份：{role}\n"
            f"{notify_status}"
            f"{response_info}"
            )
    return text, InlineKeyboardMarkup(keyboard)

# ---------- 入口 ----------
async def handle_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """个人中心入口，支持消息和回调"""
    context.user_data.pop("profile_input_state", None)

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        user = query.from_user
        msg = query.message
    else:
        user = update.effective_user
        msg = update.message

    user_id = user.id
    display_name = user.username or user.first_name or ""
    prefs = get_user_preferences(user_id)
    text, markup = await _build_profile_menu(user_id, prefs, display_name)

    if update.callback_query:
        await msg.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    else:
        await msg.reply_text(text, reply_markup=markup, parse_mode="Markdown")

    return PROFILE_MAIN


# ---------- 通知开关 ----------
async def profile_toggle_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    display_name = query.from_user.username or query.from_user.first_name or ""
    await query.answer()

    prefs = get_user_preferences(user_id)
    prefs["monitor_notify"] = not prefs["monitor_notify"]
    set_user_preference(user_id, "monitor_notify", prefs["monitor_notify"])

    text, markup = await _build_profile_menu(user_id, prefs, display_name)
    await query.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")


# ---------- 默认群发附言 ----------
async def profile_signature_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    prefs = get_user_preferences(user_id)
    current_sig = prefs.get("broadcast_signature", "")
    if current_sig:
        hint = f"当前附言：\n「{current_sig}」\n\n"
    else:
        hint = "当前没有默认附言。\n\n"

    context.user_data["profile_input_state"] = True

    await query.message.edit_text(
        hint +
        "📝 请发送新的附言内容（直接发送文字即可）。\n"
        "若要去除附言，请发送 /remove\n"
        "取消请发送 /cancel",
        parse_mode="Markdown"
    )
    return SET_SIGNATURE


async def profile_signature_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    display_name = update.effective_user.username or update.effective_user.first_name or ""
    text = update.message.text.strip()
    prefs = get_user_preferences(user_id)  # 提前获取，统一使用

    if text == '/cancel':
        await update.message.reply_text("❌ 已取消")
        _, markup = await _build_profile_menu(user_id, prefs)
        await update.message.reply_text("已返回个人中心", reply_markup=markup, parse_mode="Markdown")
        return ConversationHandler.END

    if text == '/remove':
        set_user_preference(user_id, "broadcast_signature", "")
        await update.message.reply_text("✅ 默认附言已删除")
    else:
        set_user_preference(user_id, "broadcast_signature", text)
        await update.message.reply_text(f"✅ 默认附言已设置为：\n附言：{text}")

    _, markup = await _build_profile_menu(user_id, prefs, display_name)
    await update.message.reply_text("已返回个人中心", reply_markup=markup, parse_mode="Markdown")
    return ConversationHandler.END

# ---------- 返回个人中心 ----------
async def profile_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    try:
        prefs = get_user_preferences(user_id)
        display_name = query.from_user.username or query.from_user.first_name or ""
        text, markup = await _build_profile_menu(user_id, prefs, display_name)
        await query.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except Exception:
        await context.bot.send_message(chat_id=user_id, text="请选择功能：", reply_markup=get_main_menu(user_id))
    return ConversationHandler.END

# ==================== 规则管理 ====================
# ---- 规则管理主菜单 ----
async def profile_rules_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """规则管理主菜单"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    from db import get_all_rules, get_rule_global_status
    rules = get_all_rules(active_only=True)
    rule_enabled = get_rule_global_status()

    status_text = "🟢 已启用" if rule_enabled else "🔴 已停用"

    text = "📋 **规则管理**\n\n"
    text += f"⚙️ 规则功能状态：**{status_text}**\n\n"

    if rules:
        text += f"📊 当前已添加 **{len(rules)}** 个规则：\n"
        for rule in rules[:10]:
            text += f"  📌 {rule['rule_name']}\n"
        if len(rules) > 10:
            text += f"  ... 还有 {len(rules) - 10} 个\n"
    else:
        text += "📭 暂无规则\n"

    text += "\n请选择操作："

    keyboard = [
        [InlineKeyboardButton("➕ 添加规则", callback_data="profile_rule_add")],
    ]

    if rules:
        keyboard.append([InlineKeyboardButton("📖 查看所有规则", callback_data="profile_rule_view_all")])
        keyboard.append([InlineKeyboardButton("✏️ 更新规则", callback_data="profile_rule_update_select")])
        keyboard.append([InlineKeyboardButton("🗑️ 删除规则", callback_data="profile_rule_delete_select")])

    # 全局开关按钮
    toggle_text = "🔴 停用规则功能" if rule_enabled else "🟢 启用规则功能"
    keyboard.append([InlineKeyboardButton(toggle_text, callback_data="profile_rule_global_toggle")])

    keyboard.append([InlineKeyboardButton("◀️ 返回个人中心", callback_data="profile_back_to_menu")])

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RULE_MENU

# ---- 添加规则：输入名称 ----
async def profile_rule_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """添加规则 - 输入名称"""
    query = update.callback_query
    await query.answer()

    context.user_data["profile_input_state"] = True
    context.user_data["rule_action"] = "add_name"

    keyboard = [[InlineKeyboardButton("◀️ 返回规则管理", callback_data="profile_rules_menu")]]

    await query.message.edit_text(
        "➕ **添加规则**\n\n"
        "请输入规则名称（提示词）：\n"
        "例如：德国、美国、BPay手续费 等\n\n"
        "💡 群组内输入「发送名称规则」即可查询\n"
        "例如输入：发送德国规则\n"
        "❌ 发送 /cancel 取消",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RULE_ADD_NAME

async def profile_rule_add_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收规则名称"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # ✅ 检查是否是键盘按钮
    if _is_keyboard_button(text):
        # 清理所有状态
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("rule_action", None)
        context.user_data.pop("rule_name", None)
        # 显示主菜单
        from handlers.menu import get_main_menu
        await update.message.reply_text(
            "请选择功能：",
            reply_markup=get_main_menu(user_id)
        )
        return ConversationHandler.END

    if text == '/cancel':
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("rule_action", None)
        context.user_data.pop("rule_name", None)
        await update.message.reply_text("❌ 已取消添加")
        from handlers.menu import get_main_menu
        await update.message.reply_text(
            "请选择功能：",
            reply_markup=get_main_menu(user_id)
        )
        return ConversationHandler.END

    if len(text) < 1:
        await update.message.reply_text("❌ 规则名称不能为空，请重新输入：")
        return RULE_ADD_NAME

    # 检查是否已存在
    from db import get_rule
    existing = get_rule(text)
    if existing and existing['is_active']:
        await update.message.reply_text(
            f"⚠️ 规则「{safe_escape_markdown(text)}」已存在\n"
            f"内容：{safe_escape_markdown(existing['rule_content'][:100])}\n\n"
            f"请使用其他名称，或先删除后再添加：\n"
            f"❌ 发送 /cancel 取消"
        )
        return RULE_ADD_NAME

    context.user_data["rule_name"] = text
    context.user_data["rule_action"] = "add_content"

    await update.message.reply_text(
        f"📝 规则名称：**{text}**\n\n"
        "请输入规则内容：\n"
        "例如：手续费5%，汇率7.2，使用TRC20地址...\n\n"
        "💡 支持 Markdown 格式\n"
        "❌ 发送 /cancel 取消",
        parse_mode="Markdown"
    )
    return RULE_ADD_CONTENT

async def profile_rule_add_content_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收规则内容并保存"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # ✅ 先检查是否是键盘按钮
    if _is_keyboard_button(text):
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("rule_action", None)
        context.user_data.pop("rule_name", None)
        from handlers.menu import get_main_menu
        await update.message.reply_text(
            "请选择功能：",
            reply_markup=get_main_menu(user_id)
        )
        return ConversationHandler.END

    if text == '/cancel':
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("rule_action", None)
        context.user_data.pop("rule_name", None)
        await update.message.reply_text("❌ 已取消添加")
        from handlers.menu import get_main_menu
        await update.message.reply_text(
            "请选择功能：",
            reply_markup=get_main_menu(user_id)
        )
        return ConversationHandler.END

    rule_name = context.user_data.get("rule_name", "")
    if not rule_name:
        await update.message.reply_text("❌ 会话已过期，请重新添加")
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("rule_action", None)
        return ConversationHandler.END

    from db import add_rule
    success = add_rule(rule_name, text, user_id)

    if success:
        await update.message.reply_text(
            f"✅ 规则「**{rule_name}**」已添加成功！\n\n"
            f"💡 有权限的人在群内发送「**发送{rule_name}规则**」即可查看该规则"
        )
    else:
        await update.message.reply_text("❌ 添加失败，该规则可能已存在")

    # 🔥 关键修复：在清除状态前，设置标记防止AI捕获
    context.user_data["_message_handled"] = True

    context.user_data.pop("profile_input_state", None)
    context.user_data.pop("rule_action", None)
    context.user_data.pop("rule_name", None)

    prefs = get_user_preferences(user_id)
    _, markup = await _build_profile_menu(user_id, prefs, 
                                          update.effective_user.username or update.effective_user.first_name or "")
    await update.message.reply_text("已返回个人中心", reply_markup=markup, parse_mode="Markdown")
    return ConversationHandler.END

# ---- 查看所有规则 ----
async def profile_rule_view_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看所有规则列表（可点击查看详情）"""
    query = update.callback_query
    await query.answer()

    from db import get_all_rules
    rules = get_all_rules(active_only=True)

    if not rules:
        await query.message.edit_text("📭 暂无规则")
        return RULE_MENU

    text = "📖 **规则列表**\n\n"
    text += f"共 **{len(rules)}** 个规则，点击查看详情：\n\n"

    keyboard = []
    for rule in rules:
        # 显示规则名称和内容预览（前30个字符）
        content_preview = safe_escape_markdown(rule['rule_content'][:40])
        text += f"📌 **{safe_escape_markdown(rule['rule_name'])}**\n"
        text += f"   {content_preview}{'...' if len(rule['rule_content']) > 40 else ''}\n\n"

        keyboard.append([InlineKeyboardButton(
            f"📋 {rule['rule_name']}", 
            callback_data=f"profile_rule_detail_{rule['rule_name']}"
        )])

    keyboard.append([InlineKeyboardButton("◀️ 返回规则管理", callback_data="profile_rules_menu")])

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RULE_VIEW

# ---- 更新规则：选择 ----
async def profile_rule_update_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """选择要更新的规则"""
    query = update.callback_query
    await query.answer()

    from db import get_all_rules
    rules = get_all_rules(active_only=True)

    if not rules:
        await query.message.edit_text("📭 暂无规则可更新")
        return RULE_MENU

    text = "✏️ **选择要更新的规则**\n\n"
    keyboard = []
    for rule in rules:
        text += f"📌 {safe_escape_markdown(rule['rule_name'])}\n"
        keyboard.append([InlineKeyboardButton(f"✏️ {rule['rule_name']}", callback_data=f"profile_rule_upd_{rule['rule_name']}")])

    keyboard.append([InlineKeyboardButton("◀️ 返回规则管理", callback_data="profile_rules_menu")])

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RULE_UPDATE_SELECT

async def profile_rule_update_select_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理更新规则的选择"""
    query = update.callback_query
    await query.answer()

    rule_name = query.data.replace("profile_rule_upd_", "")
    context.user_data["rule_name"] = rule_name
    context.user_data["profile_input_state"] = True
    context.user_data["rule_action"] = "update_content"

    from db import get_rule
    rule = get_rule(rule_name)
    current_content = rule['rule_content'] if rule else "无"

    keyboard = [[InlineKeyboardButton("◀️ 返回规则管理", callback_data="profile_rules_menu")]]

    await query.message.edit_text(
        f"✏️ **更新规则**\n\n"
        f"规则名称：**{rule_name}**\n"
        f"当前内容：{current_content[:200]}{'...' if len(current_content) > 200 else ''}\n\n"
        "请输入新的规则内容：\n\n"
        "❌ 发送 /cancel 取消",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RULE_UPDATE_CONTENT

async def profile_rule_update_content_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收更新的规则内容"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # ✅ 先检查是否是键盘按钮
    if _is_keyboard_button(text):
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("rule_action", None)
        context.user_data.pop("rule_name", None)
        from handlers.menu import get_main_menu
        await update.message.reply_text(
            "请选择功能：",
            reply_markup=get_main_menu(user_id)
        )
        return ConversationHandler.END

    if text == '/cancel':
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("rule_action", None)
        context.user_data.pop("rule_name", None)
        await update.message.reply_text("❌ 已取消更新")
        from handlers.menu import get_main_menu
        await update.message.reply_text(
            "请选择功能：",
            reply_markup=get_main_menu(user_id)
        )
        return ConversationHandler.END

    rule_name = context.user_data.get("rule_name", "")

    from db import update_rule
    success = update_rule(rule_name, text)

    if success:
        await update.message.reply_text(f"✅ 规则「**{rule_name}**」已更新成功！")
    else:
        await update.message.reply_text("❌ 更新失败，请稍后重试")

    # 🔥 关键修复：在清除状态前，设置标记防止AI捕获
    context.user_data["_message_handled"] = True

    context.user_data.pop("profile_input_state", None)
    context.user_data.pop("rule_action", None)
    context.user_data.pop("rule_name", None)

    prefs = get_user_preferences(user_id)
    _, markup = await _build_profile_menu(user_id, prefs, 
                                          update.effective_user.username or update.effective_user.first_name or "")
    await update.message.reply_text("已返回个人中心", reply_markup=markup, parse_mode="Markdown")
    return ConversationHandler.END

# ---- 删除规则：选择 ----
async def profile_rule_delete_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """选择要删除的规则"""
    query = update.callback_query
    await query.answer()

    from db import get_all_rules
    rules = get_all_rules(active_only=True)

    if not rules:
        await query.message.edit_text("📭 暂无规则可删除")
        return RULE_MENU

    text = "🗑️ **选择要删除的规则**\n\n"
    keyboard = []
    for rule in rules:
        text += f"📌 {rule['rule_name']}\n"
        keyboard.append([InlineKeyboardButton(f"🗑️ {rule['rule_name']}", callback_data=f"profile_rule_del_{rule['rule_name']}")])

    keyboard.append([InlineKeyboardButton("◀️ 返回规则管理", callback_data="profile_rules_menu")])

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RULE_DELETE_SELECT

async def profile_rule_delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """执行删除规则"""
    query = update.callback_query
    await query.answer()

    rule_name = query.data.replace("profile_rule_del_", "")

    from db import delete_rule
    success = delete_rule(rule_name)

    if success:
        await query.message.edit_text(f"✅ 已删除规则「{rule_name}」")
    else:
        await query.message.edit_text("❌ 删除失败，请稍后重试")

    return ConversationHandler.END

async def profile_rule_global_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """切换规则功能的全局开关"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    from db import get_rule_global_status, set_rule_global_status

    current_status = get_rule_global_status()
    new_status = not current_status

    success = set_rule_global_status(new_status)

    if success:
        status_text = "启用" if new_status else "停用"
        await query.answer(f"✅ 已{status_text}规则功能", show_alert=True)
    else:
        await query.answer("❌ 操作失败", show_alert=True)

    # 刷新菜单
    return await profile_rules_menu(update, context)

async def profile_rule_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看单个规则完整详情"""
    query = update.callback_query
    await query.answer()

    rule_name = query.data.replace("profile_rule_detail_", "")

    from db import get_rule
    from datetime import datetime

    rule = get_rule(rule_name)

    if not rule:
        await query.message.edit_text("❌ 规则不存在")
        return RULE_VIEW

    text = f"📋 **{safe_escape_markdown(rule['rule_name'])}规则**\n\n"
    text += f"{safe_escape_markdown(rule['rule_content'])}\n\n"

    created_time = datetime.fromtimestamp(rule['created_at']).strftime('%Y-%m-%d %H:%M')
    updated_time = datetime.fromtimestamp(rule['updated_at']).strftime('%Y-%m-%d %H:%M')
    text += f"📅 创建时间：{created_time}\n"
    text += f"🔄 更新时间：{updated_time}\n"

    keyboard = [
        [InlineKeyboardButton("◀️ 返回规则列表", callback_data="profile_rule_view_all")],
        [InlineKeyboardButton("◀️ 返回规则管理", callback_data="profile_rules_menu")],
    ]

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RULE_VIEW

# ---- 返回个人中心 ----
async def profile_back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """从规则管理返回个人中心"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    prefs = get_user_preferences(user_id)
    display_name = query.from_user.username or query.from_user.first_name or ""
    text, markup = await _build_profile_menu(user_id, prefs, display_name)
    await query.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    return ConversationHandler.END

# ==================== 业绩汇总 ====================
async def profile_performance_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """业绩汇总 - 直接显示当前月业绩"""
    query = update.callback_query
    user_id = query.from_user.id
    # 权限检查：仅正式操作员和管理员
    if not is_authorized(user_id, require_full_access=True):
        await query.answer("❌ 临时操作员不能使用业绩汇总功能", show_alert=True)
        return
    await query.answer()

    from db import get_performance_available_months, get_performance_summary, get_loss_records
    from datetime import datetime

    months = get_performance_available_months()

    # 当前月份
    now = datetime.now()
    current_month = f"{now.year}-{now.month:02d}"

    if not months:
        text = "📊 **业绩汇总**\n\n📭 暂无业绩记录\n\n请选择操作："
        keyboard = [
            [InlineKeyboardButton("➕ 记录业绩", callback_data="profile_performance_record"),
             InlineKeyboardButton("➖ 记录亏损", callback_data="profile_loss_record")],
            [InlineKeyboardButton("◀️ 返回个人中心", callback_data="profile_return")],
        ]
        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return PERFORMANCE_MENU

    # 默认显示当前月，如果没有则显示最近一个月
    if current_month in months:
        display_month = current_month
    else:
        display_month = months[0]

    year, month = display_month.split('-')
    year = int(year)
    month = int(month)
    summary = get_performance_summary(year, month)
    settings = summary.get('settings', {})

    # 提成比例百分比
    commission_pct = int(settings.get('commission_rate', 0.1) * 100)
    channel_commission_pct = int(settings.get('channel_commission_rate', 0.1) * 100)
    customer_commission_pct = int(settings.get('customer_commission_rate', 0.1) * 100)
    channel_loss_pct = int(settings.get('channel_loss_rate', 0.25) * 100)
    customer_loss_pct = int(settings.get('customer_loss_rate', 0.25) * 100)
    company_loss_pct = int(settings.get('company_loss_rate', 0.50) * 100)

    # 标题
    text = f"📊 **{year}年{month}月 业绩汇总**\n\n"

    # 公司总利润和本月亏损（使用引用模块）
    text += "<blockquote>"
    text += f"<b>公司总利润：{summary['total_profit']:.2f} USDT</b>\n"
    if summary.get('total_loss', 0) > 0:
        text += f"<b>本月亏损：{summary['total_loss']:.2f} USDT</b>\n"
    text += "</blockquote>\n"

    # 业绩记录表格
    if summary['records']:
        text += "<code>编号 | 利润 | 国家 | 通道 | 通道员工 | 客户 | 客户员工</code>\n"

        for r in summary['records'][:10]:
            country = r['country'][:4] if r['country'] else ''
            ch_name = r['channel_employee_name'] or f"ID{r['channel_employee_id']}"
            cu_name = r['customer_employee_name'] or f"ID{r['customer_employee_id']}"
            # 创建可点击的员工链接
            ch_link = f"<a href=\"tg://user?id={r['channel_employee_id']}\">{ch_name[:4]}</a>"
            cu_link = f"<a href=\"tg://user?id={r['customer_employee_id']}\">{cu_name[:4]}</a>"
            # 编号可点击复制
            record_id_link = f"<code>{r['id']}</code>"
            text += f"{record_id_link} | 💰{r['profit']:.0f} | {country} | +{r['channel_income']:.0f} | {ch_link} | -{abs(r['customer_expense']):.0f} | {cu_link}\n"

        if len(summary['records']) > 10:
            text += f"\n... 仅显示10条，共 {len(summary['records'])} 条（导出HTML查看全部）\n"

    # 亏损记录表格（使用引用模块）
    loss_records = summary.get('loss_records', [])
    if loss_records:
        text += "\n<blockquote>"
        text += "<b>💸 亏损记录</b>\n"
        text += "</blockquote>"
        text += "<code>编号 | 日期 | 金额 | 国家 | 通道承担 | 客户承担 | 原因</code>\n"

        for l in loss_records[:10]:
            date_str = l['date'][-5:] if l['date'] else ''
            country = l['country'][:4] if l['country'] else ''
            ch_bear = l.get('channel_bear', 0)
            cu_bear = l.get('customer_bear', 0)
            ch_name = l.get('channel_employee_name') or ''
            cu_name = l.get('customer_employee_name') or ''
            reason = (l.get('reason') or '')[:6]
            # 创建可点击的员工链接
            ch_link = f"<a href=\"tg://user?id={l['channel_employee_id']}\">{ch_name[:4]}</a>" if l.get('channel_employee_id') else ch_name[:4]
            cu_link = f"<a href=\"tg://user?id={l['customer_employee_id']}\">{cu_name[:4]}</a>" if l.get('customer_employee_id') else cu_name[:4]
            # 亏损编号显示为L+数字，可点击复制
            loss_id_link = f"<code>L{l['id']}</code>"
            text += f"{loss_id_link} | {date_str} | {l['amount']:.0f} | {country} | {ch_bear:.0f} {ch_link} | {cu_bear:.0f} {cu_link} | {reason}\n"

        if len(loss_records) > 10:
            text += f"\n... 仅显示10条，共 {len(loss_records)} 条\n"

    # 员工提成汇总（使用引用模块，员工按类型分类）
    text += "\n<blockquote>"
    text += "<b>💰 员工提成汇总</b>\n"
    text += "</blockquote>"

    employee_data = summary.get('employee_data', {})
    if employee_data:
        for emp_id, data in employee_data.items():
            gross_commission = data['commission'] - data.get('actual_base_salary', 0) - data.get('incentive', 0)
            actual_base = data.get('actual_base_salary', 0)
            incentive = data.get('incentive', 0)
            loss_bear = data['loss_bear']

            total_income = gross_commission + actual_base + incentive - loss_bear

            commission_info = f"• <a href=\"tg://user?id={emp_id}\">{data['name']}</a>：总收入 {total_income:.2f} USDT\n"

            commission_info += f"  ├─ 业绩：{data['performance']:.2f} USDT（提成：{gross_commission:.2f} USDT）\n"

            has_base_salary = data.get('base_salary', 0) > 0
            has_actual_base = actual_base > 0
            has_loss = loss_bear > 0
            has_incentive = incentive > 0

            if has_actual_base:
                base_salary = data.get('base_salary', 0)
                completion_rate = data.get('completion_rate', 0)
                if completion_rate > 0:
                    commission_info += f"  ├─ 实际底薪：{actual_base:.2f} USDT（底薪 {base_salary:.2f} USDT × 完成率 {completion_rate}%）\n"
                else:
                    commission_info += f"  ├─ 底薪：{actual_base:.2f} USDT\n"

            if has_incentive:
                threshold = data.get('incentive_threshold', 0)
                rate = data.get('incentive_rate', 0)
                commission_info += f"  ├─ 激励奖：{incentive:.2f} USDT（达到门槛 {threshold:.0f} USDT，{rate*100:.1f}%）\n"

            if has_loss:
                commission_info += f"  └─ 承担亏损：{loss_bear:.2f} USDT\n\n"
            else:
                commission_info += "\n"
            text += commission_info
    else:
        for emp_id, data in summary['employee_commission'].items():
            perf = summary['employee_performance'].get(emp_id, {}).get('performance', 0)
            text += f"• {data['name']}：{data['commission']:.2f} USDT\n"
            text += f"  └─ 业绩：{perf:.2f} USDT\n"

    # 当前比例设置（使用引用模块）
    text += "\n<blockquote>"
    text += "<b>📊 当前比例设置</b>\n"
    text += "</blockquote>"
    text += f"• 通道提成：{channel_commission_pct}% | 客户提成：{customer_commission_pct}%\n"
    text += f"• 亏损分摊：通道{channel_loss_pct}% | 客户{customer_loss_pct}% | 公司{company_loss_pct}%\n"
    text += f"💡 业绩 = 利润 × 50% | 提成 = 利润 × 提成比例 - 亏损承担\n"

    # 按钮布局（一排两个）
    keyboard = [
        [InlineKeyboardButton("➕ 记录业绩", callback_data="profile_performance_record"),
         InlineKeyboardButton("➖ 记录亏损", callback_data="profile_loss_record")],
        [InlineKeyboardButton("📅 查看其他月份", callback_data="profile_performance_view"),
         InlineKeyboardButton("📥 导出HTML", callback_data="profile_performance_export_select")],
    ]
    from config import OWNER_ID
    if user_id == OWNER_ID:
        keyboard.append([
            InlineKeyboardButton("✏️ 修改业绩", callback_data="profile_performance_edit"),
            InlineKeyboardButton("🗑️ 删除业绩", callback_data="profile_performance_delete"),
        ])
        keyboard.append([
            InlineKeyboardButton("📝 记录追溯", callback_data="profile_performance_trace"),
            InlineKeyboardButton("⚙️ 比例设置", callback_data="profile_performance_settings"),
        ])
    keyboard.append([InlineKeyboardButton("◀️ 返回个人中心", callback_data="profile_return")])

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return PERFORMANCE_MENU

async def profile_performance_record_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """记录业绩 - 输入信息"""
    query = update.callback_query
    user_id = query.from_user.id

    if not is_authorized(user_id, require_full_access=True):
        await query.answer("❌ 无权限", show_alert=True)
        return
    await query.answer()

    context.user_data["profile_input_state"] = True
    context.user_data["perf_action"] = "record"

    # 获取现有正式操作员列表
    from auth import operators as auth_operators
    employee_list = ""
    if auth_operators:
        employee_list = "\n\n📋 **现有员工列表：**\n"
        for uid, info in auth_operators.items():
            name = info.get('first_name') or ''
            uname = f" @{info['username']}" if info.get('username') else ''
            employee_list += f"• {name}{uname}（ID: `{uid}`）\n"
    else:
        employee_list = "\n\n⚠️ 暂无正式操作员，请先添加操作员"

    keyboard = [[InlineKeyboardButton("◀️ 返回业绩菜单", callback_data="profile_performance_menu")]]

    await query.message.edit_text(
        "➕ **记录业绩**\n\n"
        "请输入信息，用空格分隔：\n"
        "`国家 通道收入 客户支出 通道群名 客户群名 @通道员工 @客户员工`\n\n"
        "例如：\n"
        "`德国 5000 -3000 德国通道群 德国客户群 @张三 @李四`\n\n"
        "💡 **说明**：\n"
        "• 通道收入填正数（如5000）\n"
        "• 客户支出填负数（如-3000）\n"
        "• 利润 = 通道收入 + 客户支出\n"
        "• 员工用 @用户名 或 用户ID\n"
        "• 只能选择正式操作员\n"
        f"{employee_list}"
        "\n❌ 发送 /cancel 取消",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PERFORMANCE_RECORD


async def profile_performance_record_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收业绩记录"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # ✅ 检查是否是键盘按钮
    if _is_keyboard_button(text):
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("perf_action", None)
        from handlers.menu import get_main_menu
        await update.message.reply_text(
            "请选择功能：",
            reply_markup=get_main_menu(user_id)
        )
        return ConversationHandler.END

    if text == '/cancel':
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("perf_action", None)
        await update.message.reply_text("❌ 已取消记录")
        from handlers.menu import get_main_menu
        await update.message.reply_text(
            "请选择功能：",
            reply_markup=get_main_menu(user_id)
        )
        return ConversationHandler.END

    # ✅ 如果输入看起来不像业绩记录（太短，不含数字），可能是想退出
    if len(text.split()) < 3 and not any(c.isdigit() for c in text):
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("perf_action", None)
        from handlers.menu import get_main_menu
        await update.message.reply_text(
            "已取消业绩记录\n\n请选择功能：",
            reply_markup=get_main_menu(user_id)
        )
        return ConversationHandler.END

    # 🔥 关键修复：标记消息已处理，防止 AI 捕获
    context.user_data["_message_handled"] = True

    # 解析输入
    import shlex
    try:
        parts = shlex.split(text)
    except:
        parts = text.split()

    if len(parts) < 7:
        await update.message.reply_text(
            "❌ 格式错误，至少需要7个参数\n"
            "格式：国家 通道收入 客户支出 通道群名 客户群名 通道员工 客户员工\n\n"
            "请重新输入："
        )
        return PERFORMANCE_RECORD

    country = parts[0]
    try:
        channel_income = float(parts[1])
        customer_expense = float(parts[2])
    except ValueError:
        await update.message.reply_text("❌ 金额格式错误，请输入数字\n请重新输入：")
        return PERFORMANCE_RECORD

    channel_group = parts[3]
    customer_group = parts[4]

    # 解析员工
    channel_employee_id = 0
    channel_employee_name = ""
    customer_employee_id = 0
    customer_employee_name = ""

    # 通道员工
    ch_emp = parts[5]
    if ch_emp.startswith('@'):
        ch_username = ch_emp[1:]
        # 从操作员中查找
        from auth import operators as auth_operators
        found = False
        for oid, info in auth_operators.items():
            if info.get('username') == ch_username:
                channel_employee_id = oid
                channel_employee_name = info.get('first_name') or ch_username
                found = True
                break
        if not found:
            await update.message.reply_text(f"❌ 未找到正式操作员：{ch_emp}\n请确认用户名正确\n请重新输入：")
            return PERFORMANCE_RECORD
    elif ch_emp.isdigit():
        channel_employee_id = int(ch_emp)
        from auth import operators as auth_operators
        if channel_employee_id in auth_operators:
            channel_employee_name = auth_operators[channel_employee_id].get('first_name') or str(channel_employee_id)
        else:
            await update.message.reply_text(f"❌ 未找到正式操作员ID：{ch_emp}\n请重新输入：")
            return PERFORMANCE_RECORD
    else:
        await update.message.reply_text(f"❌ 员工格式错误：{ch_emp}\n请使用 @用户名 或 用户ID\n请重新输入：")
        return PERFORMANCE_RECORD

    # 客户员工
    cu_emp = parts[6] if len(parts) > 6 else ""
    if cu_emp.startswith('@'):
        cu_username = cu_emp[1:]
        from auth import operators as auth_operators
        found = False
        for oid, info in auth_operators.items():
            if info.get('username') == cu_username:
                customer_employee_id = oid
                customer_employee_name = info.get('first_name') or cu_username
                found = True
                break
        if not found:
            await update.message.reply_text(f"❌ 未找到正式操作员：{cu_emp}\n请重新输入：")
            return PERFORMANCE_RECORD
    elif cu_emp.isdigit():
        customer_employee_id = int(cu_emp)
        from auth import operators as auth_operators
        if customer_employee_id in auth_operators:
            customer_employee_name = auth_operators[customer_employee_id].get('first_name') or str(customer_employee_id)
        else:
            await update.message.reply_text(f"❌ 未找到正式操作员ID：{cu_emp}\n请重新输入：")
            return PERFORMANCE_RECORD
    else:
        await update.message.reply_text(f"❌ 员工格式错误：{cu_emp}\n请使用 @用户名 或 用户ID\n请重新输入：")
        return PERFORMANCE_RECORD

    # 保存记录
    from db import add_performance_record

    profit = channel_income + customer_expense
    success = add_performance_record(
        country, channel_income, customer_expense,
        channel_group, customer_group,
        channel_employee_id, channel_employee_name,
        customer_employee_id, customer_employee_name,
        user_id
    )

    if success:
        # 获取当前提成比例设置
        from db import get_performance_settings
        settings = get_performance_settings()
        channel_commission_rate = settings.get('channel_commission_rate', 0.1)
        customer_commission_rate = settings.get('customer_commission_rate', 0.1)

        ch_commission = profit * channel_commission_rate  # 通道员工提成 = 利润 × 提成比例
        cu_commission = profit * customer_commission_rate  # 客户员工提成 = 利润 × 提成比例
        ch_performance = profit * 0.5  # 业绩 = 利润 × 50%
        cu_performance = profit * 0.5  # 业绩 = 利润 × 50%

        reply = (
            f"✅ **已记录业绩！**\n\n"
            f"📋 **记录详情：**\n"
            f"• 国家：{country}\n"
            f"• 通道收入：{channel_income} USDT（群：{channel_group}）\n"
            f"• 客户支出：{customer_expense} USDT（群：{customer_group}）\n"
            f"• 利润：{profit} USDT\n\n"
            f"👤 **通道员工：{channel_employee_name}**\n"
            f"   预估提成：{ch_commission:.2f} USDT | 业绩：{ch_performance:.2f} USDT\n\n"
            f"👤 **客户员工：{customer_employee_name}**\n"
            f"   预估提成：{cu_commission:.2f} USDT | 业绩：{cu_performance:.2f} USDT\n\n"
            f"💡 **说明**：\n"
            f"• 业绩 = 利润 × 50%\n"
            f"• 通道员工提成 = 利润 × {channel_commission_rate*100:.0f}% - 亏损承担\n"
            f"• 客户员工提成 = 利润 × {customer_commission_rate*100:.0f}% - 亏损承担"
        )
        if channel_employee_id == customer_employee_id:
            reply += f"\n\n⚠️ 通道和客户为同一人，预估提成 {ch_commission + cu_commission:.2f} USDT，业绩 {ch_performance + cu_performance:.2f} USDT"

        await update.message.reply_text(reply, parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ 记录失败，请稍后重试")
        return

    context.user_data.pop("profile_input_state", None)
    context.user_data.pop("perf_action", None)
    context.user_data["_message_handled"] = True

    # 返回到业绩记录添加页面
    context.user_data["profile_input_state"] = True
    context.user_data["perf_action"] = "record"

    # 获取现有正式操作员列表
    from auth import operators as auth_operators
    employee_list = ""
    if auth_operators:
        employee_list = "\n\n📋 **现有员工列表：**\n"
        for uid, info in auth_operators.items():
            name = info.get('first_name') or ''
            uname = f" @{info['username']}" if info.get('username') else ''
            employee_list += f"• {name}{uname}（ID: `{uid}`）\n"
    else:
        employee_list = "\n\n⚠️ 暂无正式操作员，请先添加操作员"

    keyboard = [[InlineKeyboardButton("◀️ 返回业绩菜单", callback_data="profile_performance_menu")]]

    await update.message.reply_text(
        "➕ **记录业绩**\n\n"
        "请输入信息，用空格分隔：\n"
        "`国家 通道收入 客户支出 通道群名 客户群名 @通道员工 @客户员工`\n\n"
        "例如：\n"
        "`德国 5000 -3000 德国通道群 德国客户群 @张三 @李四`\n\n"
        "💡 **说明**：\n"
        "• 通道收入填正数（如5000）\n"
        "• 客户支出填负数（如-3000）\n"
        "• 利润 = 通道收入 + 客户支出\n"
        "• 员工用 @用户名 或 用户ID\n"
        "• 只能选择正式操作员\n"
        f"{employee_list}"
        "\n❌ 发送 /cancel 取消",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PERFORMANCE_RECORD


async def profile_performance_view_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看汇总 - 选择月份"""
    query = update.callback_query
    await query.answer()

    from db import get_performance_available_months

    months = get_performance_available_months()

    if not months:
        await query.message.edit_text("📭 暂无业绩记录")
        return PERFORMANCE_MENU

    keyboard = []
    for m in months[:12]:
        year, month = m.split('-')
        keyboard.append([InlineKeyboardButton(
            f"📅 {year}年{int(month)}月",
            callback_data=f"perf_month_{m}"
        )])

    keyboard.append([InlineKeyboardButton("◀️ 返回业绩菜单", callback_data="profile_performance_menu")])

    await query.message.edit_text(
        "📊 **查看业绩汇总**\n\n请选择月份：",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PERFORMANCE_MONTH_SELECT


async def profile_performance_view_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示指定月份的业绩汇总"""
    query = update.callback_query
    await query.answer()

    month_str = query.data.replace("perf_month_", "")
    year, month = month_str.split('-')
    year = int(year)
    month = int(month)

    from db import get_performance_summary
    summary = get_performance_summary(year, month)
    settings = summary.get('settings', {})

    # 提成比例百分比
    commission_pct = int(settings.get('commission_rate', 0.1) * 100)
    channel_commission_pct = int(settings.get('channel_commission_rate', 0.1) * 100)
    customer_commission_pct = int(settings.get('customer_commission_rate', 0.1) * 100)
    channel_loss_pct = int(settings.get('channel_loss_rate', 0.25) * 100)
    customer_loss_pct = int(settings.get('customer_loss_rate', 0.25) * 100)
    company_loss_pct = int(settings.get('company_loss_rate', 0.50) * 100)

    # 标题
    text = f"📊 **{year}年{month}月 业绩汇总**\n\n"

    # 公司总利润和本月亏损（使用引用模块）
    text += "<blockquote>"
    text += f"<b>公司总利润：{summary['total_profit']:.2f} USDT</b>\n"
    if summary.get('total_loss', 0) > 0:
        text += f"<b>本月亏损：{summary['total_loss']:.2f} USDT</b>\n"
    text += "</blockquote>\n"

    # 业绩记录表格
    if summary['records']:
        text += "<code>编号 | 利润 | 国家 | 通道 | 通道员工 | 客户 | 客户员工</code>\n"

        for r in summary['records'][:10]:
            country = r['country'][:4] if r['country'] else ''
            ch_name = r['channel_employee_name'] or f"ID{r['channel_employee_id']}"
            cu_name = r['customer_employee_name'] or f"ID{r['customer_employee_id']}"
            # 创建可点击的员工链接
            ch_link = f"<a href=\"tg://user?id={r['channel_employee_id']}\">{ch_name[:4]}</a>"
            cu_link = f"<a href=\"tg://user?id={r['customer_employee_id']}\">{cu_name[:4]}</a>"
            # 编号可点击复制
            record_id_link = f"<code>{r['id']}</code>"
            text += f"{record_id_link} | 💰{r['profit']:.0f} | {country} | +{r['channel_income']:.0f} | {ch_link} | -{abs(r['customer_expense']):.0f} | {cu_link}\n"

        if len(summary['records']) > 10:
            text += f"\n... 仅显示10条，共 {len(summary['records'])} 条（导出HTML查看全部）\n"

    # 亏损记录表格（使用引用模块）
    loss_records = summary.get('loss_records', [])
    if loss_records:
        text += "\n<blockquote>"
        text += "<b>💸 亏损记录</b>\n"
        text += "</blockquote>"
        text += "<code>编号 | 日期 | 金额 | 国家 | 通道承担 | 客户承担 | 原因</code>\n"

        for l in loss_records[:10]:
            date_str = l['date'][-5:] if l['date'] else ''
            country = l['country'][:4] if l['country'] else ''
            ch_bear = l.get('channel_bear', 0)
            cu_bear = l.get('customer_bear', 0)
            ch_name = l.get('channel_employee_name') or ''
            cu_name = l.get('customer_employee_name') or ''
            reason = (l.get('reason') or '')[:6]
            # 创建可点击的员工链接
            ch_link = f"<a href=\"tg://user?id={l['channel_employee_id']}\">{ch_name[:4]}</a>" if l.get('channel_employee_id') else ch_name[:4]
            cu_link = f"<a href=\"tg://user?id={l['customer_employee_id']}\">{cu_name[:4]}</a>" if l.get('customer_employee_id') else cu_name[:4]
            # 亏损编号显示为L+数字，可点击复制
            loss_id_link = f"<code>L{l['id']}</code>"
            text += f"{loss_id_link} | {date_str} | {l['amount']:.0f} | {country} | {ch_bear:.0f} {ch_link} | {cu_bear:.0f} {cu_link} | {reason}\n"

        if len(loss_records) > 10:
            text += f"\n... 仅显示10条，共 {len(loss_records)} 条\n"

    # 员工提成汇总（使用引用模块，员工按类型分类）
    text += "\n<blockquote>"
    text += "<b>💰 员工提成汇总</b>\n"
    text += "</blockquote>"

    employee_data = summary.get('employee_data', {})
    if employee_data:
        for emp_id, data in employee_data.items():
            gross_commission = data['commission'] - data.get('actual_base_salary', 0) - data.get('incentive', 0)
            actual_base = data.get('actual_base_salary', 0)
            incentive = data.get('incentive', 0)
            loss_bear = data['loss_bear']

            total_income = gross_commission + actual_base + incentive - loss_bear

            commission_info = f"• <a href=\"tg://user?id={emp_id}\">{data['name']}</a>：总收入 {total_income:.2f} USDT\n"

            commission_info += f"  ├─ 业绩：{data['performance']:.2f} USDT（提成：{gross_commission:.2f} USDT）\n"

            has_base_salary = data.get('base_salary', 0) > 0
            has_actual_base = actual_base > 0
            has_loss = loss_bear > 0
            has_incentive = incentive > 0

            if has_actual_base:
                base_salary = data.get('base_salary', 0)
                completion_rate = data.get('completion_rate', 0)
                if completion_rate > 0:
                    commission_info += f"  ├─ 实际底薪：{actual_base:.2f} USDT（底薪 {base_salary:.2f} USDT × 完成率 {completion_rate}%）\n"
                else:
                    commission_info += f"  ├─ 底薪：{actual_base:.2f} USDT\n"

            if has_incentive:
                threshold = data.get('incentive_threshold', 0)
                rate = data.get('incentive_rate', 0)
                commission_info += f"  ├─ 激励奖：{incentive:.2f} USDT（达到门槛 {threshold:.0f} USDT，{rate*100:.1f}%）\n"

            if has_loss:
                commission_info += f"  └─ 承担亏损：{loss_bear:.2f} USDT\n\n"
            else:
                commission_info += "\n"
            text += commission_info
    else:
        for emp_id, data in summary['employee_commission'].items():
            perf = summary['employee_performance'].get(emp_id, {}).get('performance', 0)
            text += f"• {data['name']}：{data['commission']:.2f} USDT\n"
            text += f"  └─ 业绩：{perf:.2f} USDT\n"

    # 当前比例设置（使用引用模块）
    text += "\n<blockquote>"
    text += "<b>📊 当前比例设置</b>\n"
    text += "</blockquote>"
    text += f"• 通道提成：{channel_commission_pct}% | 客户提成：{customer_commission_pct}%\n"
    text += f"• 亏损分摊：通道{channel_loss_pct}% | 客户{customer_loss_pct}% | 公司{company_loss_pct}%\n"
    text += f"💡 业绩 = 利润 × 50% | 提成 = 利润 × 提成比例 - 亏损承担\n"

    keyboard = [[InlineKeyboardButton("◀️ 返回月份选择", callback_data="profile_performance_view")]]
    keyboard.append([InlineKeyboardButton("◀️ 返回业绩汇总", callback_data="profile_performance_menu")])

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return PERFORMANCE_VIEW

# ---- 修改业绩 ----
async def profile_performance_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """修改记录 - 输入信息（自动识别业绩/亏损）"""
    query = update.callback_query
    user_id = query.from_user.id
    from config import OWNER_ID
    if user_id != OWNER_ID:
        await query.answer("❌ 只有控制人才能修改", show_alert=True)
        return

    await query.answer()
    context.user_data["profile_input_state"] = True
    context.user_data["perf_action"] = "edit"

    # 获取现有正式操作员列表
    from auth import operators as auth_operators
    employee_list = ""
    if auth_operators:
        employee_list = "\n\n📋 **现有员工列表：**\n"
        for uid, info in auth_operators.items():
            name = info.get('first_name') or ''
            uname = f" @{info['username']}" if info.get('username') else ''
            employee_list += f"• {name}{uname}（ID: `{uid}`）\n"

    keyboard = [[InlineKeyboardButton("◀️ 返回", callback_data="profile_performance_menu")]]

    await query.message.edit_text(
        "✏️ **修改记录**\n\n"
        "系统会根据编号自动识别业绩或亏损：\n\n"
        "**修改业绩格式：**\n"
        "`编号 国家 通道收入 客户支出 通道群名 客户群名 @通道员工 @客户员工`\n\n"
        "例如：\n"
        "`1 德国 5000 -3000 德国通道群 德国客户群 @张三 @李四`\n\n"
        "**修改亏损格式：**\n"
        "`编号 金额 国家 @通道员工 @客户员工 原因`\n\n"
        "例如：\n"
        "`L1 3000 埃塞 @萧诧 @谢文东 跑路`\n\n"
        "💡 业绩编号是数字（如 1、2）\n"
        "💡 亏损编号是 L+数字（如 L1、L2）\n"
        f"{employee_list}"
        "\n❌ 发送 /cancel 取消",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PERFORMANCE_EDIT


async def profile_edit_performance_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """修改业绩 - 输入信息"""
    query = update.callback_query
    user_id = query.from_user.id
    from config import OWNER_ID
    if user_id != OWNER_ID:
        await query.answer("❌ 只有控制人才能修改业绩", show_alert=True)
        return

    await query.answer()
    context.user_data["profile_input_state"] = True
    context.user_data["perf_action"] = "edit_performance"

    from auth import operators as auth_operators
    employee_list = ""
    if auth_operators:
        employee_list = "\n\n📋 **现有员工列表：**\n"
        for uid, info in auth_operators.items():
            name = info.get('first_name') or ''
            uname = f" @{info['username']}" if info.get('username') else ''
            employee_list += f"• {name}{uname}（ID: `{uid}`）\n"

    keyboard = [[InlineKeyboardButton("◀️ 返回", callback_data="profile_performance_edit")]]

    await query.message.edit_text(
        "✏️ **修改业绩**\n\n"
        "请输入信息，用空格分隔：\n"
        "`编号 国家 通道收入 客户支出 通道群名 客户群名 @通道员工 @客户员工`\n\n"
        "例如：\n"
        "`1 德国 5000 -3000 德国通道群 德国客户群 @张三 @李四`\n\n"
        "💡 编号是汇总列表中第一列的序号\n"
        f"{employee_list}"
        "\n❌ 发送 /cancel 取消",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PERFORMANCE_EDIT


async def profile_edit_loss_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """修改亏损 - 输入信息"""
    query = update.callback_query
    user_id = query.from_user.id
    from config import OWNER_ID
    if user_id != OWNER_ID:
        await query.answer("❌ 只有控制人才能修改亏损", show_alert=True)
        return

    await query.answer()
    context.user_data["profile_input_state"] = True
    context.user_data["perf_action"] = "edit_loss"

    # 获取现有正式操作员列表
    from auth import operators as auth_operators
    employee_list = ""
    if auth_operators:
        employee_list = "\n\n📋 **现有员工列表：**\n"
        for uid, info in auth_operators.items():
            name = info.get('first_name') or ''
            uname = f" @{info['username']}" if info.get('username') else ''
            employee_list += f"• {name}{uname}（ID: `{uid}`）\n"

    keyboard = [[InlineKeyboardButton("◀️ 返回", callback_data="profile_performance_edit")]]

    await query.message.edit_text(
        "✏️ **修改亏损**\n\n"
        "请输入信息，用空格分隔：\n"
        "`编号 金额 国家 @通道员工 @客户员工 原因`\n\n"
        "例如：\n"
        "`L1 3000 埃塞 @萧诧 @谢文东 跑路`\n\n"
        "💡 编号是亏损列表中的编号（如 L1、L2）\n"
        "💡 员工用 @用户名 或 用户ID\n"
        f"{employee_list}"
        "\n❌ 发送 /cancel 取消",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PERFORMANCE_EDIT


async def profile_performance_edit_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收修改的记录（自动识别业绩/亏损）"""
    user_id = update.effective_user.id
    from config import OWNER_ID
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ 只有控制人才能修改")
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("perf_action", None)
        return ConversationHandler.END

    text = update.message.text.strip()

    # 检查是否是键盘按钮
    if _is_keyboard_button(text):
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("perf_action", None)
        from handlers.menu import get_main_menu
        await update.message.reply_text("请选择功能：", reply_markup=get_main_menu(user_id))
        return ConversationHandler.END

    if text == '/cancel':
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("perf_action", None)
        await update.message.reply_text("❌ 已取消修改")
        from handlers.menu import get_main_menu
        await update.message.reply_text("请选择功能：", reply_markup=get_main_menu(user_id))
        return ConversationHandler.END

    context.user_data["_message_handled"] = True

    import shlex
    try:
        parts = shlex.split(text)
    except:
        parts = text.split()

    # 自动识别：L开头是亏损，纯数字是业绩
    is_loss = parts[0].upper().startswith('L')

    # 处理亏损修改
    if is_loss:
        if len(parts) < 6:
            await update.message.reply_text("❌ 亏损格式错误，至少需要6个参数\n请重新输入：")
            return PERFORMANCE_EDIT

        record_id = parts[0]  # 亏损编号是字符串，如 L1
        try:
            amount = float(parts[1])
        except ValueError:
            await update.message.reply_text("❌ 金额格式错误\n请重新输入：")
            return PERFORMANCE_EDIT

        country = parts[2]

        # 解析通道员工
        channel_employee_id = 0
        channel_employee_name = ""
        ch_emp = parts[3]
        if ch_emp.startswith('@'):
            ch_username = ch_emp[1:]
            from auth import operators as auth_operators
            for oid, info in auth_operators.items():
                if info.get('username') == ch_username:
                    channel_employee_id = oid
                    channel_employee_name = info.get('first_name') or ch_username
                    break
        elif ch_emp.isdigit():
            channel_employee_id = int(ch_emp)
            from auth import operators as auth_operators
            if channel_employee_id in auth_operators:
                channel_employee_name = auth_operators[channel_employee_id].get('first_name') or str(channel_employee_id)

        # 解析客户员工
        customer_employee_id = 0
        customer_employee_name = ""
        cu_emp = parts[4]
        if cu_emp.startswith('@'):
            cu_username = cu_emp[1:]
            from auth import operators as auth_operators
            for oid, info in auth_operators.items():
                if info.get('username') == cu_username:
                    customer_employee_id = oid
                    customer_employee_name = info.get('first_name') or cu_username
                    break
        elif cu_emp.isdigit():
            customer_employee_id = int(cu_emp)
            from auth import operators as auth_operators
            if customer_employee_id in auth_operators:
                customer_employee_name = auth_operators[customer_employee_id].get('first_name') or str(customer_employee_id)

        reason = parts[5] if len(parts) > 5 else ""

        from db import get_loss_record_by_id, update_loss_record
        record = get_loss_record_by_id(record_id)
        if not record:
            await update.message.reply_text(f"❌ 未找到编号 {record_id} 的亏损记录\n请重新输入：")
            return PERFORMANCE_EDIT

        success = update_loss_record(
            record_id, amount, country,
            channel_employee_id, channel_employee_name,
            customer_employee_id, customer_employee_name,
            reason, user_id
        )

        if success:
            await update.message.reply_text(f"✅ 已修改编号 {record_id} 的亏损记录")
        else:
            await update.message.reply_text("❌ 修改失败")
            return PERFORMANCE_EDIT

    # 处理业绩修改
    else:
        if len(parts) < 8:
            await update.message.reply_text("❌ 业绩格式错误，至少需要8个参数\n请重新输入：")
            return PERFORMANCE_EDIT

        try:
            record_id = int(parts[0])
        except ValueError:
            await update.message.reply_text("❌ 编号必须是数字\n请重新输入：")
            return PERFORMANCE_EDIT

        from db import get_performance_record_by_id, update_performance_record
        record = get_performance_record_by_id(record_id)
        if not record:
            await update.message.reply_text(f"❌ 未找到编号 {record_id} 的业绩记录\n请重新输入：")
            return PERFORMANCE_EDIT

        country = parts[1]
        try:
            channel_income = float(parts[2])
            customer_expense = float(parts[3])
        except ValueError:
            await update.message.reply_text("❌ 金额格式错误\n请重新输入：")
            return PERFORMANCE_EDIT

        channel_group = parts[4]
        customer_group = parts[5]

        # 解析员工
        channel_employee_id = 0
        channel_employee_name = ""
        customer_employee_id = 0
        customer_employee_name = ""

        ch_emp = parts[6]
        if ch_emp.startswith('@'):
            ch_username = ch_emp[1:]
            from auth import operators as auth_operators
            for oid, info in auth_operators.items():
                if info.get('username') == ch_username:
                    channel_employee_id = oid
                    channel_employee_name = info.get('first_name') or ch_username
                    break
        elif ch_emp.isdigit():
            channel_employee_id = int(ch_emp)
            from auth import operators as auth_operators
            if channel_employee_id in auth_operators:
                channel_employee_name = auth_operators[channel_employee_id].get('first_name') or str(channel_employee_id)

        cu_emp = parts[7]
        if cu_emp.startswith('@'):
            cu_username = cu_emp[1:]
            from auth import operators as auth_operators
            for oid, info in auth_operators.items():
                if info.get('username') == cu_username:
                    customer_employee_id = oid
                    customer_employee_name = info.get('first_name') or cu_username
                    break
        elif cu_emp.isdigit():
            customer_employee_id = int(cu_emp)
            from auth import operators as auth_operators
            if customer_employee_id in auth_operators:
                customer_employee_name = auth_operators[customer_employee_id].get('first_name') or str(customer_employee_id)

        success = update_performance_record(
            record_id, country, channel_income, customer_expense,
            channel_group, customer_group,
            channel_employee_id, channel_employee_name,
            customer_employee_id, customer_employee_name,
            operated_by=user_id
        )

        if success:
            await update.message.reply_text(f"✅ 已修改编号 {record_id} 的业绩记录")
        else:
            await update.message.reply_text("❌ 修改失败")
            return PERFORMANCE_EDIT

    context.user_data.pop("profile_input_state", None)
    context.user_data.pop("perf_action", None)
    context.user_data["_message_handled"] = True

    # 返回到修改记录页面
    context.user_data["profile_input_state"] = True
    context.user_data["perf_action"] = "edit"

    # 获取现有正式操作员列表
    from auth import operators as auth_operators
    employee_list = ""
    if auth_operators:
        employee_list = "\n\n📋 **现有员工列表：**\n"
        for uid, info in auth_operators.items():
            name = info.get('first_name') or ''
            uname = f" @{info['username']}" if info.get('username') else ''
            employee_list += f"• {name}{uname}（ID: `{uid}`）\n"

    keyboard = [[InlineKeyboardButton("◀️ 返回", callback_data="profile_performance_menu")]]

    await update.message.reply_text(
        "✏️ **修改记录**\n\n"
        "系统会根据编号自动识别业绩或亏损：\n\n"
        "**修改业绩格式：**\n"
        "`编号 国家 通道收入 客户支出 通道群名 客户群名 @通道员工 @客户员工`\n\n"
        "例如：\n"
        "`1 德国 5000 -3000 德国通道群 德国客户群 @张三 @李四`\n\n"
        "**修改亏损格式：**\n"
        "`编号 金额 国家 @通道员工 @客户员工 原因`\n\n"
        "例如：\n"
        "`L1 3000 埃塞 @萧诧 @谢文东 跑路`\n\n"
        "💡 业绩编号是数字（如 1、2）\n"
        "💡 亏损编号是 L+数字（如 L1、L2）\n"
        f"{employee_list}"
        "\n❌ 发送 /cancel 取消",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PERFORMANCE_EDIT


# ---- 删除业绩 ----
async def profile_performance_delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """删除记录 - 输入编号（自动识别业绩/亏损）"""
    query = update.callback_query
    user_id = query.from_user.id
    from config import OWNER_ID
    if user_id != OWNER_ID:
        await query.answer("❌ 只有控制人才能删除", show_alert=True)
        return

    await query.answer()
    context.user_data["profile_input_state"] = True
    context.user_data["perf_action"] = "delete"

    keyboard = [[InlineKeyboardButton("◀️ 返回", callback_data="profile_performance_menu")]]

    await query.message.edit_text(
        "🗑️ **删除记录**\n\n"
        "请输入要删除的编号：\n\n"
        "• 业绩编号：`1`、`2` 等\n"
        "• 亏损编号：`L1`、`L2` 等\n\n"
        "💡 系统会根据编号自动识别类型\n"
        "❌ 发送 /cancel 取消",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PERFORMANCE_DELETE


async def profile_delete_performance_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """删除业绩 - 输入编号"""
    query = update.callback_query
    user_id = query.from_user.id
    from config import OWNER_ID
    if user_id != OWNER_ID:
        await query.answer("❌ 只有控制人才能删除业绩", show_alert=True)
        return

    await query.answer()
    context.user_data["profile_input_state"] = True
    context.user_data["perf_action"] = "delete_performance"

    keyboard = [[InlineKeyboardButton("◀️ 返回", callback_data="profile_performance_delete")]]

    await query.message.edit_text(
        "🗑️ **删除业绩**\n\n"
        "请输入要删除的业绩编号：\n"
        "例如：`1`\n\n"
        "💡 编号是汇总列表中第一列的序号\n"
        "❌ 发送 /cancel 取消",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PERFORMANCE_DELETE


async def profile_delete_loss_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """删除亏损 - 输入编号"""
    query = update.callback_query
    user_id = query.from_user.id
    from config import OWNER_ID
    if user_id != OWNER_ID:
        await query.answer("❌ 只有控制人才能删除亏损", show_alert=True)
        return

    await query.answer()
    context.user_data["profile_input_state"] = True
    context.user_data["perf_action"] = "delete_loss"

    keyboard = [[InlineKeyboardButton("◀️ 返回", callback_data="profile_performance_delete")]]

    await query.message.edit_text(
        "🗑️ **删除亏损**\n\n"
        "请输入要删除的亏损编号：\n"
        "例如：`L1`\n\n"
        "💡 编号是亏损列表中的编号（如 L1、L2）\n"
        "❌ 发送 /cancel 取消",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PERFORMANCE_DELETE


async def profile_performance_delete_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收删除编号（自动识别业绩/亏损）"""
    user_id = update.effective_user.id
    from config import OWNER_ID
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ 只有控制人才能删除")
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("perf_action", None)
        return ConversationHandler.END

    text = update.message.text.strip()

    if text == '/cancel':
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("perf_action", None)
        await update.message.reply_text("❌ 已取消删除")
        from handlers.menu import get_main_menu
        await update.message.reply_text("请选择功能：", reply_markup=get_main_menu(user_id))
        return ConversationHandler.END

    context.user_data["_message_handled"] = True

    # 自动识别：L开头是亏损，纯数字是业绩
    is_loss = text.upper().startswith('L')

    if is_loss:
        # 删除亏损
        from db import get_loss_record_by_id, delete_loss_record
        record = get_loss_record_by_id(text)
        if not record:
            await update.message.reply_text(f"❌ 未找到编号 {text} 的亏损记录\n请重新输入：")
            return PERFORMANCE_DELETE

        if delete_loss_record(text, operated_by=user_id):
            await update.message.reply_text(f"✅ 已删除编号 {text} 的亏损记录")
        else:
            await update.message.reply_text("❌ 删除失败")
            return PERFORMANCE_DELETE
    else:
        # 删除业绩
        if not text.isdigit():
            await update.message.reply_text("❌ 业绩编号必须是数字，亏损编号以L开头\n请重新输入：")
            return PERFORMANCE_DELETE

        record_id = int(text)

        from db import get_performance_record_by_id, delete_performance_record
        record = get_performance_record_by_id(record_id)
        if not record:
            await update.message.reply_text(f"❌ 未找到编号 {record_id} 的业绩记录\n请重新输入：")
            return PERFORMANCE_DELETE

        if delete_performance_record(record_id, operated_by=user_id):
            await update.message.reply_text(f"✅ 已删除编号 {record_id} 的业绩记录")
        else:
            await update.message.reply_text("❌ 删除失败")
            return PERFORMANCE_DELETE

    context.user_data.pop("profile_input_state", None)
    context.user_data.pop("perf_action", None)
    context.user_data["_message_handled"] = True

    # 返回到删除记录页面
    context.user_data["profile_input_state"] = True
    context.user_data["perf_action"] = "delete"

    keyboard = [[InlineKeyboardButton("◀️ 返回", callback_data="profile_performance_menu")]]

    await update.message.reply_text(
        "🗑️ **删除记录**\n\n"
        "请输入要删除的编号：\n\n"
        "• 业绩编号：`1`、`2` 等\n"
        "• 亏损编号：`L1`、`L2` 等\n\n"
        "💡 系统会根据编号自动识别类型\n"
        "❌ 发送 /cancel 取消",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PERFORMANCE_DELETE

async def profile_performance_export_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """导出业绩 - 选择月份"""
    query = update.callback_query
    await query.answer()

    from db import get_performance_available_months

    months = get_performance_available_months()
    if not months:
        await query.message.edit_text("📭 暂无业绩记录可导出")
        return PERFORMANCE_MENU

    keyboard = []
    for m in months[:12]:
        year, month = m.split('-')
        keyboard.append([InlineKeyboardButton(
            f"📅 {year}年{int(month)}月",
            callback_data=f"perf_export_{m}"
        )])

    keyboard.append([InlineKeyboardButton("📥 导出全部", callback_data="perf_export_all")])
    keyboard.append([InlineKeyboardButton("◀️ 返回业绩汇总", callback_data="profile_performance_menu")])

    await query.message.edit_text(
        "📥 **导出业绩汇总**\n\n请选择要导出的月份，或导出全部：",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PERFORMANCE_MONTH_SELECT

async def profile_performance_export_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """执行导出"""
    query = update.callback_query
    data = query.data

    if data == "perf_export_all":
        # 导出全部
        from db import get_performance_records
        records = get_performance_records()
        if not records:
            await query.answer("暂无业绩记录", show_alert=True)
            return
        year_str = "全部"
        month_str = ""
        total_profit = sum(r['profit'] for r in records)

        # 按员工汇总
        employee_commission = {}
        employee_performance = {}
        for r in records:
            profit = r['profit']
            for emp_id, emp_name, key_prefix in [
                (r['channel_employee_id'], r['channel_employee_name'], 'ch'),
                (r['customer_employee_id'], r['customer_employee_name'], 'cu')
            ]:
                if emp_id not in employee_commission:
                    employee_commission[emp_id] = {"name": emp_name or f"ID{emp_id}", "commission": 0}
                    employee_performance[emp_id] = {"name": emp_name or f"ID{emp_id}", "performance": 0}
                employee_commission[emp_id]["commission"] += profit * 0.1
                employee_performance[emp_id]["performance"] += profit / 2
    else:
        month_str = data.replace("perf_export_", "")
        year, month = month_str.split('-')
        year = int(year)
        month = int(month)
        year_str = f"{year}年{month}月"

        from db import get_performance_summary
        summary = get_performance_summary(year, month)
        records = summary['records']
        total_profit = summary['total_profit']
        employee_commission = summary['employee_commission']
        employee_performance = summary['employee_performance']
        loss_records = summary.get('loss_records', [])
        settings = summary.get('settings', {})

    await query.answer("正在生成HTML...")

    # 生成HTML
    html = generate_performance_html(records, total_profit, employee_commission, employee_performance, year_str, month_str, loss_records, settings, summary.get('employee_data'))

    import tempfile, os
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', encoding='utf-8', delete=False) as f:
        f.write(html)
        temp_path = f.name

    try:
        with open(temp_path, 'rb') as f:
            await query.message.reply_document(
                document=f,
                filename=f"业绩汇总_{year_str}.html",
                caption=f"📊 {year_str}业绩汇总已导出"
            )
    finally:
        os.unlink(temp_path)


def generate_performance_html(records, total_profit, employee_commission, employee_performance, title, subtitle="", loss_records=None, settings=None, employee_data=None):
    """生成业绩HTML"""
    total_loss = sum(l['amount'] for l in loss_records) if loss_records else 0
    commission_pct = int((settings or {}).get('commission_rate', 0.1) * 100)
    channel_commission_pct = int((settings or {}).get('channel_commission_rate', 0.1) * 100)
    customer_commission_pct = int((settings or {}).get('customer_commission_rate', 0.1) * 100)
    channel_loss_pct = int((settings or {}).get('channel_loss_rate', 0.25) * 100)
    customer_loss_pct = int((settings or {}).get('customer_loss_rate', 0.25) * 100)
    company_loss_pct = int((settings or {}).get('company_loss_rate', 0.50) * 100)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>{title} 业绩汇总</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0f172a, #1e3a5f);
            min-height: 100vh; padding: 40px 20px; color: #e2e8f0;
        }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        .header {{
            text-align: center; padding: 30px; background: rgba(255,255,255,0.05);
            border-radius: 20px; margin-bottom: 30px; backdrop-filter: blur(10px);
        }}
        .header h1 {{ font-size: 28px; background: linear-gradient(135deg, #f59e0b, #ef4444); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        .header .profit {{ font-size: 36px; font-weight: bold; color: #10b981; margin-top: 10px; }}
        .header .loss {{ font-size: 24px; color: #ef4444; margin-top: 8px; }}
        .table-container {{
            background: rgba(255,255,255,0.05); border-radius: 16px; padding: 20px;
            margin-bottom: 30px; backdrop-filter: blur(10px); overflow-x: auto;
        }}
        .section-title {{ color: #f59e0b; font-size: 20px; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 2px solid rgba(245,158,11,0.3); }}
        table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
        th {{
            background: rgba(245,158,11,0.2); padding: 14px 12px; text-align: left;
            font-weight: 600; color: #f59e0b; border-bottom: 2px solid rgba(245,158,11,0.3);
            white-space: nowrap;
        }}
        td {{ padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.06); }}
        tr:hover {{ background: rgba(255,255,255,0.03); }}
        .income {{ color: #10b981; }}
        .expense {{ color: #ef4444; }}
        .profit-cell {{ color: #f59e0b; font-weight: 600; }}
        .loss-cell {{ color: #ef4444; font-weight: 600; }}
        .employee-section {{
            background: rgba(255,255,255,0.05); border-radius: 16px; padding: 24px;
            margin-bottom: 30px; backdrop-filter: blur(10px);
        }}
        .employee-section h2 {{ color: #f59e0b; margin-bottom: 16px; }}
        .employee-card {{
            display: flex; justify-content: space-between; align-items: center;
            padding: 16px; margin-bottom: 10px; background: rgba(255,255,255,0.03);
            border-radius: 12px; border: 1px solid rgba(255,255,255,0.06);
        }}
        .employee-name {{ font-size: 16px; font-weight: 600; }}
        .employee-commission {{ color: #10b981; font-size: 18px; font-weight: bold; }}
        .employee-perf {{ color: #94a3b8; font-size: 14px; margin-left: 10px; }}
        .employee-loss {{ color: #ef4444; font-size: 14px; margin-left: 10px; }}
        .employee-incentive {{ color: #8b5cf6; font-size: 14px; margin-left: 10px; }}
        .settings-section {{
            background: rgba(255,255,255,0.05); border-radius: 16px; padding: 24px;
            margin-bottom: 30px; backdrop-filter: blur(10px);
        }}
        .settings-section h2 {{ color: #f59e0b; margin-bottom: 16px; }}
        .settings-item {{ padding: 8px 0; color: #94a3b8; }}
        .footer {{ text-align: center; color: #64748b; font-size: 12px; padding: 20px; }}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>📊 {title} 业绩汇总</h1>
        <div class="profit">公司总利润：{total_profit:.2f} USDT</div>
        {f'<div class="loss">📉 本月亏损：{total_loss:.2f} USDT</div>' if total_loss > 0 else ''}
    </div>
    <div class="table-container">
        <div class="section-title">📈 业绩记录</div>
        <table>
            <thead>
                <tr>
                    <th>编号</th><th>日期</th><th>国家</th><th>通道群名</th><th>客户群名</th><th>通道收入</th><th>客户支出</th><th>利润</th><th>通道员工</th><th>客户员工</th>
                </tr>
            </thead>
            <tbody>
"""
    for r in records:
        ch_name = r.get('channel_employee_name') or f"ID{r.get('channel_employee_id')}"
        cu_name = r.get('customer_employee_name') or f"ID{r.get('customer_employee_id')}"
        html += f"""                <tr>
                    <td>{r.get('id', '')}</td><td>{r.get('date', '')}</td><td>{r.get('country', '')}</td>
                    <td>{r.get('channel_group', '')}</td><td>{r.get('customer_group', '')}</td>
                    <td class="income">{r.get('channel_income', 0):.0f}</td>
                    <td class="expense">{r.get('customer_expense', 0):.0f}</td>
                    <td class="profit-cell">{r.get('profit', 0):.0f}</td>
                    <td>{ch_name}</td><td>{cu_name}</td>
                </tr>
"""
    html += """            </tbody>
        </table>
    </div>
"""

    # 亏损记录表格
    if loss_records:
        html += """    <div class="table-container">
        <div class="section-title">💸 亏损记录</div>
        <table>
            <thead>
                <tr>
                    <th>编号</th><th>日期</th><th>金额</th><th>国家</th><th>通道承担</th><th>客户承担</th><th>公司承担</th><th>原因</th>
                </tr>
            </thead>
            <tbody>
"""
        for l in loss_records:
            ch_name = l.get('channel_employee_name', '')
            cu_name = l.get('customer_employee_name', '')
            html += f"""                <tr>
                    <td>{l.get('id', '')}</td><td>{l.get('date', '')}</td>
                    <td class="loss-cell">{l.get('amount', 0):.0f}</td><td>{l.get('country', '')}</td>
                    <td class="expense">{l.get('channel_bear', 0):.0f} {ch_name}</td>
                    <td class="expense">{l.get('customer_bear', 0):.0f} {cu_name}</td>
                    <td class="expense">{l.get('company_bear', 0):.0f}</td>
                    <td>{l.get('reason', '')}</td>
                </tr>
"""
        html += """            </tbody>
        </table>
    </div>
"""

    html += """    <div class="employee-section">
        <h2>💰 员工提成汇总</h2>
"""
    for emp_id, data in employee_commission.items():
        emp_data = employee_data.get(emp_id, {}) if employee_data else {}

        perf = emp_data.get('performance', employee_performance.get(emp_id, {}).get('performance', 0))
        gross_commission = emp_data.get('commission', data['commission']) - emp_data.get('actual_base_salary', 0) - emp_data.get('incentive', 0)
        actual_base = emp_data.get('actual_base_salary', 0)
        incentive = emp_data.get('incentive', 0)
        loss_bear = emp_data.get('loss_bear', 0)

        total_income = gross_commission + actual_base + incentive - loss_bear

        details = f"<span class=\"employee-perf\">业绩 {perf:.2f} USDT（提成 {gross_commission:.2f} USDT）</span>"

        base_salary = emp_data.get('base_salary', 0)
        completion_rate = emp_data.get('completion_rate', 0)
        if actual_base > 0:
            if completion_rate > 0:
                details += f"<span class=\"employee-base\">实际底薪 {actual_base:.2f} USDT（底薪 {base_salary:.2f} USDT × 完成率 {completion_rate}%）</span>"
            else:
                details += f"<span class=\"employee-base\">底薪 {actual_base:.2f} USDT</span>"

        incentive_threshold = emp_data.get('incentive_threshold', 0)
        incentive_rate = emp_data.get('incentive_rate', 0)
        if incentive > 0:
            details += f"<span class=\"employee-incentive\">激励奖 {incentive:.2f} USDT（达到门槛 {incentive_threshold:.0f} USDT，{incentive_rate*100:.1f}%）</span>"

        if loss_bear > 0:
            details += f"<span class=\"employee-loss\">承担亏损 {loss_bear:.2f} USDT</span>"

        html += f"""        <div class="employee-card">
            <span class="employee-name">{data['name']}</span>
            <span class="employee-total">总收入 {total_income:.2f} USDT</span>
            <span class="employee-details">
                {details}
            </span>
        </div>
"""

    # 比例设置
    html += f"""    </div>
    <div class="settings-section">
        <h2>📊 当前比例设置</h2>
        <div class="settings-item">• 通道提成：{channel_commission_pct}% | 客户提成：{customer_commission_pct}%</div>
        <div class="settings-item">• 亏损分摊：通道{channel_loss_pct}% | 客户{customer_loss_pct}% | 公司{company_loss_pct}%</div>
    </div>
    <div class="footer">由记账机器人自动生成 · 业绩=利润×50% · 提成=利润×提成比例-亏损承担</div>
</div>
</body>
</html>"""
    return html

async def profile_performance_trace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """记录追溯 - 显示操作日志（支持分页）"""
    query = update.callback_query
    user_id = query.from_user.id

    from config import OWNER_ID
    if user_id != OWNER_ID:
        await query.answer("❌ 只有控制人才能查看", show_alert=True)
        return

    await query.answer()

    from db import get_performance_logs, get_performance_logs_count
    from datetime import datetime, timezone, timedelta
    from auth import operators as auth_operators
    import json

    # 每页显示10条
    PAGE_SIZE = 10

    # 获取当前页码（从回调数据中解析）
    page = 1
    if query.data and 'page=' in query.data:
        try:
            page = int(query.data.split('page=')[1])
        except:
            page = 1

    beijing_tz = timezone(timedelta(hours=8))
    now = datetime.now(beijing_tz)
    current_month_start = int(datetime(now.year, now.month, 1, tzinfo=beijing_tz).timestamp())

    # 获取所有操作日志（不限制数量，用于筛选本月数据）
    logs = get_performance_logs(limit=1000)

    # 筛选本月的日志，只保留业绩和亏损记录，不包含设置
    month_logs = [l for l in logs if l.get('operated_at', 0) >= current_month_start and l.get('record_type') in ['performance', 'loss']]

    total_count = len(month_logs)
    total_pages = (total_count + PAGE_SIZE - 1) // PAGE_SIZE

    # 处理分页
    start_idx = (page - 1) * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    current_page_logs = month_logs[start_idx:end_idx]

    if not month_logs:
        await query.message.edit_text(
            f"📝 记录追溯 - {now.strftime('%Y年%m月')}\n\n📭 本月暂无操作记录",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ 返回业绩汇总", callback_data="profile_performance_menu")]])
        )
        return PERFORMANCE_MENU

    # 清理特殊字符的函数
    def clean_text(t):
        if not t:
            return ''
        return t.replace('_', '').replace('*', '').replace('[', '').replace(']', '').replace('`', '').replace('(', '').replace(')', '')

    # 获取操作人名称
    def get_user_name(uid):
        if uid in auth_operators:
            name = clean_text(auth_operators[uid].get('first_name', ''))
            uname = clean_text(auth_operators[uid].get('username', ''))
            return f"{name}({uname})" if uname else name or str(uid)
        return f"ID{uid}"

    # 操作类型映射
    action_map = {'create': '创建', 'update': '修改', 'delete': '删除'}
    type_map = {'performance': '业绩', 'loss': '亏损'}

    text = f"📝 记录追溯 - {now.strftime('%Y年%m月')}\n"
    text += f"共 {total_count} 条记录 | 第 {page}/{total_pages} 页\n\n"

    for i, l in enumerate(current_page_logs, start=start_idx + 1):
        op_date = datetime.fromtimestamp(l['operated_at'], tz=beijing_tz).strftime('%m-%d')
        op_time = datetime.fromtimestamp(l['operated_at'], tz=beijing_tz).strftime('%H:%M')
        operator = get_user_name(l['operated_by'])
        action = action_map.get(l['action'], l['action'])
        record_type = type_map.get(l['record_type'], l['record_type'])
        record_id = l['record_id']

        text += f"{i}. {record_type}{action}\n"
        text += f"   日期：{op_date} | 时间：{op_time}\n"
        text += f"   编号：{record_id} | 操作人：{operator}\n"

        # 显示详细信息
        data_source = l.get('new_data') if l['action'] in ['create', 'update'] else l.get('old_data')
        if data_source:
            try:
                data = json.loads(data_source) if isinstance(data_source, str) else data_source
                if l['record_type'] == 'performance':
                    country = clean_text(data.get('country', ''))
                    profit = data.get('profit', 0)
                    ch_income = data.get('channel_income', 0)
                    cu_expense = data.get('customer_expense', 0)
                    ch_name = clean_text(data.get('channel_employee_name', ''))
                    cu_name = clean_text(data.get('customer_employee_name', ''))
                    text += f"   国家：{country} | 利润：{profit:.0f}\n"
                    text += f"   通道：{ch_income:.0f} | 客户：{cu_expense:.0f}\n"
                    text += f"   通道员工：{ch_name} | 客户员工：{cu_name}\n"
                elif l['record_type'] == 'loss':
                    amount = data.get('amount', 0)
                    country = clean_text(data.get('country', ''))
                    reason = clean_text(data.get('reason', ''))
                    ch_name = clean_text(data.get('channel_employee_name', ''))
                    cu_name = clean_text(data.get('customer_employee_name', ''))
                    text += f"   国家：{country} | 金额：{amount:.0f}\n"
                    text += f"   通道员工：{ch_name} | 客户员工：{cu_name}\n"
                    text += f"   原因：{reason}\n"
            except:
                pass
        text += "\n"

    # 构建分页键盘
    keyboard = []

    # 分页按钮
    page_buttons = []
    if page > 1:
        page_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"profile_performance_trace_page={page-1}"))
    if page < total_pages:
        page_buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"profile_performance_trace_page={page+1}"))

    if page_buttons:
        keyboard.append(page_buttons)

    # 返回按钮
    keyboard.append([InlineKeyboardButton("◀️ 返回业绩汇总", callback_data="profile_performance_menu")])

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return PERFORMANCE_MENU

async def profile_loss_record_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """记录亏损 - 输入信息"""
    query = update.callback_query
    user_id = query.from_user.id

    if not is_authorized(user_id, require_full_access=True):
        await query.answer("❌ 无权限", show_alert=True)
        return

    await query.answer()

    context.user_data["profile_input_state"] = True
    context.user_data["perf_action"] = "loss_record"

    # 获取现有正式操作员列表
    from auth import operators as auth_operators
    employee_list = ""
    if auth_operators:
        employee_list = "\n\n📋 **现有员工列表：**\n"
        for uid, info in auth_operators.items():
            name = info.get('first_name') or ''
            uname = f" @{info['username']}" if info.get('username') else ''
            employee_list += f"• {name}{uname}（ID: `{uid}`）\n"
    else:
        employee_list = "\n\n⚠️ 暂无正式操作员，请先添加操作员"

    keyboard = [[InlineKeyboardButton("◀️ 返回业绩菜单", callback_data="profile_performance_menu")]]

    await query.message.edit_text(
        "➖ **记录亏损**\n\n"
        "请输入信息，用空格分隔：\n"
        "`金额 国家 @通道员工 @客户员工 原因`\n\n"
        "例如：\n"
        "`2238 埃塞 @萧诧 @谢文东 跑路`\n\n"
        "💡 **说明**：\n"
        "• 金额填正数（如2238）\n"
        "• 员工用 @用户名 或 用户ID\n"
        "• 只能选择正式操作员\n"
        f"{employee_list}"
        "\n❌ 发送 /cancel 取消",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return LOSS_RECORD


async def profile_loss_record_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收亏损记录"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # 检查是否是键盘按钮
    if _is_keyboard_button(text):
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("perf_action", None)
        from handlers.menu import get_main_menu
        await update.message.reply_text("请选择功能：", reply_markup=get_main_menu(user_id))
        return ConversationHandler.END

    if text == '/cancel':
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("perf_action", None)
        await update.message.reply_text("❌ 已取消记录")
        from handlers.menu import get_main_menu
        await update.message.reply_text("请选择功能：", reply_markup=get_main_menu(user_id))
        return ConversationHandler.END

    context.user_data["_message_handled"] = True

    import shlex
    try:
        parts = shlex.split(text)
    except:
        parts = text.split()

    if len(parts) < 4:
        await update.message.reply_text("❌ 格式错误，至少需要4个参数\n请重新输入：")
        return LOSS_RECORD

    try:
        amount = float(parts[0])
    except ValueError:
        await update.message.reply_text("❌ 金额必须是数字\n请重新输入：")
        return LOSS_RECORD

    country = parts[1]

    # 解析通道员工
    ch_emp = parts[2]
    channel_employee_id = 0
    channel_employee_name = ""

    if ch_emp.startswith('@'):
        ch_username = ch_emp[1:]
        from auth import operators as auth_operators
        for oid, info in auth_operators.items():
            if info.get('username') == ch_username:
                channel_employee_id = oid
                channel_employee_name = info.get('first_name') or ch_username
                break
        if channel_employee_id == 0:
            await update.message.reply_text(f"❌ 未找到正式操作员：{ch_emp}\n请重新输入：")
            return LOSS_RECORD
    elif ch_emp.isdigit():
        channel_employee_id = int(ch_emp)
        from auth import operators as auth_operators
        if channel_employee_id in auth_operators:
            channel_employee_name = auth_operators[channel_employee_id].get('first_name') or str(channel_employee_id)
        else:
            await update.message.reply_text(f"❌ 未找到正式操作员ID：{ch_emp}\n请重新输入：")
            return LOSS_RECORD
    else:
        await update.message.reply_text(f"❌ 员工格式错误：{ch_emp}\n请使用 @用户名 或 用户ID\n请重新输入：")
        return LOSS_RECORD

    # 解析客户员工
    cu_emp = parts[3]
    customer_employee_id = 0
    customer_employee_name = ""

    if cu_emp.startswith('@'):
        cu_username = cu_emp[1:]
        from auth import operators as auth_operators
        for oid, info in auth_operators.items():
            if info.get('username') == cu_username:
                customer_employee_id = oid
                customer_employee_name = info.get('first_name') or cu_username
                break
        if customer_employee_id == 0:
            await update.message.reply_text(f"❌ 未找到正式操作员：{cu_emp}\n请重新输入：")
            return LOSS_RECORD
    elif cu_emp.isdigit():
        customer_employee_id = int(cu_emp)
        from auth import operators as auth_operators
        if customer_employee_id in auth_operators:
            customer_employee_name = auth_operators[customer_employee_id].get('first_name') or str(customer_employee_id)
        else:
            await update.message.reply_text(f"❌ 未找到正式操作员ID：{cu_emp}\n请重新输入：")
            return LOSS_RECORD
    else:
        await update.message.reply_text(f"❌ 员工格式错误：{cu_emp}\n请使用 @用户名 或 用户ID\n请重新输入：")
        return LOSS_RECORD

    # 原因（可选）
    reason = " ".join(parts[4:]) if len(parts) > 4 else ""

    # 保存记录
    from db import add_loss_record

    record_id = add_loss_record(
        amount=amount,
        country=country,
        channel_employee_id=channel_employee_id,
        channel_employee_name=channel_employee_name,
        customer_employee_id=customer_employee_id,
        customer_employee_name=customer_employee_name,
        reason=reason,
        created_by=user_id
    )

    if record_id:
        # 获取分摊金额
        from db import get_loss_record_by_id
        loss_record = get_loss_record_by_id(record_id)
        ch_bear = loss_record.get('channel_bear', 0)
        cu_bear = loss_record.get('customer_bear', 0)
        company_bear = loss_record.get('company_bear', 0)

        reply = (
            f"✅ **已记录亏损！**\n\n"
            f"📋 **记录详情：**\n"
            f"• 编号：{record_id}\n"
            f"• 国家：{country}\n"
            f"• 金额：{amount} USDT\n"
            f"• 原因：{reason or '无'}\n\n"
            f"💸 **分摊明细：**\n"
            f"• 通道员工({channel_employee_name})：{ch_bear:.2f} USDT\n"
            f"• 客户员工({customer_employee_name})：{cu_bear:.2f} USDT\n"
            f"• 公司承担：{company_bear:.2f} USDT"
        )
        await update.message.reply_text(reply, parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ 记录失败，请稍后重试")
        return

    context.user_data.pop("profile_input_state", None)
    context.user_data.pop("perf_action", None)
    context.user_data["_message_handled"] = True

    # 返回到亏损记录添加页面
    context.user_data["profile_input_state"] = True
    context.user_data["perf_action"] = "loss_record"

    # 获取现有正式操作员列表
    from auth import operators as auth_operators
    employee_list = ""
    if auth_operators:
        employee_list = "\n\n📋 **现有员工列表：**\n"
        for uid, info in auth_operators.items():
            name = info.get('first_name') or ''
            uname = f" @{info['username']}" if info.get('username') else ''
            employee_list += f"• {name}{uname}（ID: `{uid}`）\n"
    else:
        employee_list = "\n\n⚠️ 暂无正式操作员，请先添加操作员"

    keyboard = [[InlineKeyboardButton("◀️ 返回业绩菜单", callback_data="profile_performance_menu")]]

    await update.message.reply_text(
        "➖ **记录亏损**\n\n"
        "请输入信息，用空格分隔：\n"
        "`金额 国家 @通道员工 @客户员工 原因`\n\n"
        "例如：\n"
        "`2238 埃塞 @萧诧 @谢文东 跑路`\n\n"
        "💡 **说明**：\n"
        "• 金额填正数（如2238）\n"
        "• 员工用 @用户名 或 用户ID\n"
        "• 只能选择正式操作员\n"
        f"{employee_list}"
        "\n❌ 发送 /cancel 取消",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return LOSS_RECORD


# ==================== 比例设置功能 ====================

async def profile_performance_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """比例设置"""
    query = update.callback_query
    user_id = query.from_user.id

    from config import OWNER_ID
    if user_id != OWNER_ID:
        await query.answer("❌ 只有控制人才能修改比例设置", show_alert=True)
        return

    await query.answer()

    from db import get_performance_settings
    settings = get_performance_settings()

    commission_pct = int(settings.get('commission_rate', 0.1) * 100)
    channel_commission_pct = int(settings.get('channel_commission_rate', 0.1) * 100)
    customer_commission_pct = int(settings.get('customer_commission_rate', 0.1) * 100)
    channel_loss_pct = int(settings.get('channel_loss_rate', 0.25) * 100)
    customer_loss_pct = int(settings.get('customer_loss_rate', 0.25) * 100)
    company_loss_pct = int(settings.get('company_loss_rate', 0.50) * 100)

    incentive_tiers_str = settings.get('incentive_tiers', '')
    incentive_display = "未设置"
    if incentive_tiers_str:
        try:
            import json
            tiers = json.loads(incentive_tiers_str)
            if isinstance(tiers, list) and tiers:
                sorted_tiers = sorted(tiers, key=lambda x: x.get('threshold', 0))
                tier_texts = []
                for tier in sorted_tiers:
                    threshold = tier.get('threshold', 0)
                    rate = tier.get('rate', 0) * 100
                    tier_texts.append(f"{threshold} USDT→{rate:.0f}%")
                incentive_display = " | ".join(tier_texts)
        except:
            incentive_display = "设置有误"

    text = "⚙️ **比例设置**\n\n"
    text += f"当前设置：\n"
    text += f"• 通道员工提成比例：{channel_commission_pct}%\n"
    text += f"• 客户员工提成比例：{customer_commission_pct}%\n"
    text += f"• 亏损分摊：通道{channel_loss_pct}% | 客户{customer_loss_pct}% | 公司{company_loss_pct}%\n"
    text += f"• 激励奖励：{incentive_display}\n\n"
    text += "💡 **提成计算公式**：\n"
    text += "• 业绩 = 利润 × 50%\n"
    text += "• 通道员工提成 = 利润 × 通道提成比例 - 亏损承担\n"
    text += "• 客户员工提成 = 利润 × 客户提成比例 - 亏损承担\n\n"
    text += "请选择要修改的项目："

    keyboard = [
        [InlineKeyboardButton(f"通道提成: {channel_commission_pct}%", callback_data="profile_set_channel_commission"),
         InlineKeyboardButton(f"客户提成: {customer_commission_pct}%", callback_data="profile_set_customer_commission")],
        [InlineKeyboardButton("亏损分摊", callback_data="profile_set_loss"),
         InlineKeyboardButton(f"激励奖励: {incentive_display[:15]}", callback_data="profile_set_incentive")],
        [InlineKeyboardButton("◀️ 返回业绩汇总", callback_data="profile_performance_menu")],
    ]

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PERFORMANCE_SETTINGS


async def profile_set_commission_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置提成比例"""
    query = update.callback_query
    user_id = query.from_user.id

    from config import OWNER_ID
    if user_id != OWNER_ID:
        await query.answer("❌ 无权限", show_alert=True)
        return

    await query.answer()

    context.user_data['profile_input_state'] = 'set_commission'

    await query.message.edit_text(
        "⚙️ **设置提成比例**\n\n"
        "💡 提成计算：业绩 = 利润 × 50%\n"
        "提成 = 利润 × 提成比例 - 亏损承担\n\n"
        "请输入提成比例（百分比，如 20 表示 20%）：",
        parse_mode="Markdown"
    )
    return PERFORMANCE_SETTINGS


async def profile_set_channel_commission_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置通道员工提成比例"""
    query = update.callback_query
    user_id = query.from_user.id

    from config import OWNER_ID
    if user_id != OWNER_ID:
        await query.answer("❌ 无权限", show_alert=True)
        return

    await query.answer()

    context.user_data['profile_input_state'] = 'set_channel_commission'

    await query.message.edit_text(
        "⚙️ **设置通道员工提成比例**\n\n"
        "💡 提成计算：业绩 = 利润 × 50%\n"
        "通道员工提成 = 利润 × 提成比例 - 亏损承担\n\n"
        "请输入通道员工的提成比例（百分比，如 10 表示 10%）：",
        parse_mode="Markdown"
    )
    return PERFORMANCE_SETTINGS


async def profile_set_customer_commission_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置客户员工提成比例"""
    query = update.callback_query
    user_id = query.from_user.id

    from config import OWNER_ID
    if user_id != OWNER_ID:
        await query.answer("❌ 无权限", show_alert=True)
        return

    await query.answer()

    context.user_data['profile_input_state'] = 'set_customer_commission'

    await query.message.edit_text(
        "⚙️ **设置客户员工提成比例**\n\n"
        "💡 提成计算：业绩 = 利润 × 50%\n"
        "客户员工提成 = 利润 × 提成比例 - 亏损承担\n\n"
        "请输入客户员工的提成比例（百分比，如 10 表示 10%）：",
        parse_mode="Markdown"
    )
    return PERFORMANCE_SETTINGS


async def profile_set_loss_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置亏损分摊比例"""
    query = update.callback_query
    user_id = query.from_user.id

    from config import OWNER_ID
    if user_id != OWNER_ID:
        await query.answer("❌ 无权限", show_alert=True)
        return

    await query.answer()

    context.user_data['profile_input_state'] = 'set_loss'

    await query.message.edit_text(
        "⚙️ **设置亏损分摊比例**\n\n请输入三个比例（通道 客户 公司），用空格分隔：\n\n例如：`25 25 50`\n（三者之和应为100%）",
        parse_mode="Markdown"
    )
    return PERFORMANCE_SETTINGS


async def profile_set_incentive_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置激励奖励阶梯"""
    query = update.callback_query
    user_id = query.from_user.id

    from config import OWNER_ID
    if user_id != OWNER_ID:
        await query.answer("❌ 无权限", show_alert=True)
        return

    await query.answer()

    context.user_data['profile_input_state'] = 'set_incentive'

    await query.message.edit_text(
        "⚙️ **设置激励奖励阶梯**\n\n"
        "请输入阶梯设置，每行一个阶梯：\n"
        "`业绩门槛USDT 奖励比例%`\n\n"
        "例如：\n"
        "`5000 1`\n"
        "`10000 2`\n\n"
        "表示：业绩≥5000USDT奖励1%，业绩≥10000USDT奖励2%\n"
        "💡 阶梯从高到低匹配，取最高达标阶梯\n"
        "❌ 发送 /cancel 取消，发送 /clear 清空设置",
        parse_mode="Markdown"
    )
    return PERFORMANCE_SETTINGS


async def profile_settings_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """保存比例设置"""
    user_id = update.effective_user.id

    from config import OWNER_ID
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ 无权限")
        context.user_data.pop('profile_input_state', None)
        return ConversationHandler.END

    state = context.user_data.get('profile_input_state')
    if not state or not state.startswith('set_'):
        return

    context.user_data['_message_handled'] = True  # 标记消息已处理，防止AI识别

    text = update.message.text.strip()

    from db import update_performance_settings, get_performance_settings
    current = get_performance_settings()

    saved = False
    error_msg = None

    if state == 'set_commission':
        try:
            pct = float(text)
            if pct < 0 or pct > 100:
                error_msg = "❌ 比例必须在 0-100 之间"
                context.user_data['profile_input_state'] = 'set_commission'
            else:
                rate = pct / 100
                update_performance_settings(
                    commission_rate=rate,
                    channel_commission_rate=current.get('channel_commission_rate', 0.1),
                    customer_commission_rate=current.get('customer_commission_rate', 0.1),
                    channel_loss_rate=current['channel_loss_rate'],
                    customer_loss_rate=current['customer_loss_rate'],
                    company_loss_rate=current['company_loss_rate'],
                    updated_by=user_id
                )
                await update.message.reply_text(f"✅ 提成比例已更新为 {pct:.0f}%")
                saved = True
        except ValueError:
            error_msg = "❌ 请输入有效的数字"
            context.user_data['profile_input_state'] = 'set_commission'

    elif state == 'set_channel_commission':
        try:
            pct = float(text)
            if pct < 0 or pct > 100:
                error_msg = "❌ 比例必须在 0-100 之间"
                context.user_data['profile_input_state'] = 'set_channel_commission'
            else:
                rate = pct / 100
                update_performance_settings(
                    commission_rate=current['commission_rate'],
                    channel_commission_rate=rate,
                    customer_commission_rate=current.get('customer_commission_rate', 0.1),
                    channel_loss_rate=current['channel_loss_rate'],
                    customer_loss_rate=current['customer_loss_rate'],
                    company_loss_rate=current['company_loss_rate'],
                    updated_by=user_id
                )
                await update.message.reply_text(f"✅ 通道员工提成比例已更新为 {pct:.0f}%")
                saved = True
        except ValueError:
            error_msg = "❌ 请输入有效的数字"
            context.user_data['profile_input_state'] = 'set_channel_commission'

    elif state == 'set_customer_commission':
        try:
            pct = float(text)
            if pct < 0 or pct > 100:
                error_msg = "❌ 比例必须在 0-100 之间"
                context.user_data['profile_input_state'] = 'set_customer_commission'
            else:
                rate = pct / 100
                update_performance_settings(
                    commission_rate=current['commission_rate'],
                    channel_commission_rate=current.get('channel_commission_rate', 0.1),
                    customer_commission_rate=rate,
                    channel_loss_rate=current['channel_loss_rate'],
                    customer_loss_rate=current['customer_loss_rate'],
                    company_loss_rate=current['company_loss_rate'],
                    updated_by=user_id
                )
                await update.message.reply_text(f"✅ 客户员工提成比例已更新为 {pct:.0f}%")
                saved = True
        except ValueError:
            error_msg = "❌ 请输入有效的数字"
            context.user_data['profile_input_state'] = 'set_customer_commission'

    elif state == 'set_loss':
        parts = text.split()
        if len(parts) != 3:
            error_msg = "❌ 请输入三个比例，用空格分隔"
            context.user_data['profile_input_state'] = 'set_loss'
        else:
            try:
                ch_pct = float(parts[0])
                cu_pct = float(parts[1])
                co_pct = float(parts[2])

                total = ch_pct + cu_pct + co_pct
                if abs(total - 100) > 0.1:
                    error_msg = f"❌ 三个比例之和必须为100%，当前为 {total:.0f}%"
                    context.user_data['profile_input_state'] = 'set_loss'
                else:
                    update_performance_settings(
                        commission_rate=current['commission_rate'],
                        channel_commission_rate=current.get('channel_commission_rate', 0.1),
                        customer_commission_rate=current.get('customer_commission_rate', 0.1),
                        channel_loss_rate=ch_pct / 100,
                        customer_loss_rate=cu_pct / 100,
                        company_loss_rate=co_pct / 100,
                        updated_by=user_id
                    )
                    await update.message.reply_text(f"✅ 亏损分摊比例已更新：通道{ch_pct:.0f}% | 客户{cu_pct:.0f}% | 公司{co_pct:.0f}%")
                    saved = True
            except ValueError:
                error_msg = "❌ 请输入有效的数字"
                context.user_data['profile_input_state'] = 'set_loss'

    elif state == 'set_incentive':
        if text == '/clear':
            from db import update_incentive_tiers
            update_incentive_tiers('', user_id)
            await update.message.reply_text("✅ 激励奖励设置已清空")
            saved = True
        else:
            lines = text.strip().split('\n')
            tiers = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) != 2:
                    error_msg = "❌ 每行必须包含两个数字：业绩门槛和奖励比例"
                    context.user_data['profile_input_state'] = 'set_incentive'
                    break
                try:
                    threshold = float(parts[0])
                    rate = float(parts[1]) / 100
                    if threshold < 0:
                        error_msg = "❌ 业绩门槛不能为负数"
                        context.user_data['profile_input_state'] = 'set_incentive'
                        break
                    if rate < 0 or rate > 1:
                        error_msg = "❌ 奖励比例必须在 0-100 之间"
                        context.user_data['profile_input_state'] = 'set_incentive'
                        break
                    tiers.append({'threshold': threshold, 'rate': rate})
                except ValueError:
                    error_msg = "❌ 请输入有效的数字"
                    context.user_data['profile_input_state'] = 'set_incentive'
                    break
            if not error_msg:
                if not tiers:
                    error_msg = "❌ 请至少输入一个阶梯设置"
                    context.user_data['profile_input_state'] = 'set_incentive'
                else:
                    import json
                    tiers_str = json.dumps(tiers)
                    from db import update_incentive_tiers
                    update_incentive_tiers(tiers_str, user_id)
                    sorted_tiers = sorted(tiers, key=lambda x: x['threshold'])
                    tier_texts = [f"{t['threshold']:.0f}USDT→{t['rate']*100:.0f}%" for t in sorted_tiers]
                    await update.message.reply_text(f"✅ 激励奖励阶梯已更新：{' | '.join(tier_texts)}")
                    saved = True

    if error_msg:
        await update.message.reply_text(error_msg)
        # 返回到比例设置页面
        settings = get_performance_settings()
        commission_pct = int(settings.get('commission_rate', 0.1) * 100)
        channel_commission_pct = int(settings.get('channel_commission_rate', 0.1) * 100)
        customer_commission_pct = int(settings.get('customer_commission_rate', 0.1) * 100)
        channel_loss_pct = int(settings.get('channel_loss_rate', 0.25) * 100)
        customer_loss_pct = int(settings.get('customer_loss_rate', 0.25) * 100)
        company_loss_pct = int(settings.get('company_loss_rate', 0.50) * 100)

        incentive_tiers_str = settings.get('incentive_tiers', '')
        incentive_display = "未设置"
        if incentive_tiers_str:
            try:
                import json
                tiers = json.loads(incentive_tiers_str)
                if isinstance(tiers, list) and tiers:
                    sorted_tiers = sorted(tiers, key=lambda x: x.get('threshold', 0))
                    tier_texts = []
                    for tier in sorted_tiers:
                        threshold = tier.get('threshold', 0)
                        rate = tier.get('rate', 0) * 100
                        tier_texts.append(f"{threshold} USDT→{rate:.0f}%")
                    incentive_display = " | ".join(tier_texts)
            except:
                incentive_display = "设置有误"

        text = "⚙️ **比例设置**\n\n"
        text += f"当前设置：\n"
        text += f"• 通道员工提成比例：{channel_commission_pct}%\n"
        text += f"• 客户员工提成比例：{customer_commission_pct}%\n"
        text += f"• 亏损分摊：通道{channel_loss_pct}% | 客户{customer_loss_pct}% | 公司{company_loss_pct}%\n"
        text += f"• 激励奖励：{incentive_display}\n\n"
        text += "💡 **提成计算公式**：\n"
        text += "• 业绩 = 利润 × 50%\n"
        text += "• 通道员工提成 = 利润 × 通道提成比例 - 亏损承担\n"
        text += "• 客户员工提成 = 利润 × 客户提成比例 - 亏损承担\n\n"
        text += "请选择要修改的项目："

        keyboard = [
            [InlineKeyboardButton(f"通道提成: {channel_commission_pct}%", callback_data="profile_set_channel_commission"),
             InlineKeyboardButton(f"客户提成: {customer_commission_pct}%", callback_data="profile_set_customer_commission")],
            [InlineKeyboardButton("亏损分摊", callback_data="profile_set_loss"),
             InlineKeyboardButton(f"激励奖励: {incentive_display[:15]}", callback_data="profile_set_incentive")],
            [InlineKeyboardButton("◀️ 返回业绩汇总", callback_data="profile_performance_menu")],
        ]

        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return PERFORMANCE_SETTINGS

    # 保存成功后返回到比例设置页面
    context.user_data.pop('profile_input_state', None)

    settings = get_performance_settings()
    commission_pct = int(settings.get('commission_rate', 0.1) * 100)
    channel_commission_pct = int(settings.get('channel_commission_rate', 0.1) * 100)
    customer_commission_pct = int(settings.get('customer_commission_rate', 0.1) * 100)
    channel_loss_pct = int(settings.get('channel_loss_rate', 0.25) * 100)
    customer_loss_pct = int(settings.get('customer_loss_rate', 0.25) * 100)
    company_loss_pct = int(settings.get('company_loss_rate', 0.50) * 100)

    incentive_tiers_str = settings.get('incentive_tiers', '')
    incentive_display = "未设置"
    if incentive_tiers_str:
        try:
            import json
            tiers = json.loads(incentive_tiers_str)
            if isinstance(tiers, list) and tiers:
                sorted_tiers = sorted(tiers, key=lambda x: x.get('threshold', 0))
                tier_texts = []
                for tier in sorted_tiers:
                    threshold = tier.get('threshold', 0)
                    rate = tier.get('rate', 0) * 100
                    tier_texts.append(f"{threshold} USDT→{rate:.0f}%")
                incentive_display = " | ".join(tier_texts)
        except:
            incentive_display = "设置有误"

    text = "⚙️ **比例设置**\n\n"
    text += f"当前设置：\n"
    text += f"• 通道员工提成比例：{channel_commission_pct}%\n"
    text += f"• 客户员工提成比例：{customer_commission_pct}%\n"
    text += f"• 亏损分摊：通道{channel_loss_pct}% | 客户{customer_loss_pct}% | 公司{company_loss_pct}%\n"
    text += f"• 激励奖励：{incentive_display}\n\n"
    text += "💡 **提成计算公式**：\n"
    text += "• 业绩 = 利润 × 50%\n"
    text += "• 通道员工提成 = 利润 × 通道提成比例 - 亏损承担\n"
    text += "• 客户员工提成 = 利润 × 客户提成比例 - 亏损承担\n\n"
    text += "请选择要修改的项目："

    keyboard = [
        [InlineKeyboardButton(f"通道提成: {channel_commission_pct}%", callback_data="profile_set_channel_commission"),
         InlineKeyboardButton(f"客户提成: {customer_commission_pct}%", callback_data="profile_set_customer_commission")],
        [InlineKeyboardButton("亏损分摊", callback_data="profile_set_loss"),
         InlineKeyboardButton(f"激励奖励: {incentive_display[:15]}", callback_data="profile_set_incentive")],
        [InlineKeyboardButton("◀️ 返回业绩汇总", callback_data="profile_performance_menu")],
    ]

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PERFORMANCE_SETTINGS

async def profile_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消所有个人中心相关操作"""
    user_id = update.effective_user.id

    # 清除所有相关状态
    context.user_data.pop("profile_input_state", None)
    context.user_data.pop("rule_action", None)
    context.user_data.pop("rule_name", None)
    context.user_data.pop("perf_action", None)
    context.user_data.pop("_message_handled", None)

    await update.message.reply_text("❌ 已取消")

    from handlers.menu import get_main_menu
    await update.message.reply_text("请选择功能：", reply_markup=get_main_menu(user_id))
    return ConversationHandler.END
