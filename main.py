# main.py - 完整修复版
try:
    import pysqlite3
    import sys
    sys.modules['sqlite3'] = pysqlite3
    print("✅ Replit 环境：使用 pysqlite3")
except ImportError:
    pass  # 服务器环境，使用默认 sqlite3

import asyncio
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler,
    ChatMemberHandler
)
from config import BOT_TOKEN
from auth import is_authorized, init_operators_from_db
from db import init_db, save_group, delete_group_from_db, DB_PATH, get_monitored_addresses
from handlers.start import start
from handlers import monitor, operator, usdt, accounting, broadcast, transfer
from auth import cmd_update_operator_info
from handlers.git_update import get_git_handlers
from handlers.group_manager import (
    group_manager_menu, show_stats, list_categories,
    add_category_start, delete_category_start,
    delete_category_confirm, set_group_category_start,
    select_group_for_category, set_group_category,
    handle_text_input,
    cleanup_expired_states
)
from handlers.menu import get_main_menu
from handlers.accounting import get_service_message_handler
from handlers.ai_client import get_ai_client
from handlers.help import handle_help
from handlers.profile import (
    handle_profile, profile_stats, profile_addresses,
    profile_toggle_notify, profile_signature_start, profile_signature_input,
    profile_contact, profile_feedback_start, profile_feedback_input,
    profile_export_data, profile_back, profile_report_toggle,   # 添加 profile_report_toggle
    SET_SIGNATURE, FEEDBACK
)

from datetime import datetime, timedelta, timezone   # 新增这一行


# ==================== 辅助键盘函数 ====================
def get_monitor_keyboard(user_id: int):
    """获取监控模块键盘"""
    from db import get_monitored_addresses as get_addrs
    addresses = get_addrs(user_id=user_id)
    keyboard = [[KeyboardButton("➕ 添加监控地址")]]
    if addresses:
        keyboard.append([KeyboardButton("📋 监控列表"), KeyboardButton("📊 月度统计")])
        keyboard.append([KeyboardButton("❌ 删除监控地址")])
    keyboard.append([KeyboardButton("◀️ 返回主菜单")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_operator_keyboard(user_id: int):
    """获取操作人管理键盘"""
    from config import OWNER_ID
    if user_id == OWNER_ID:
        keyboard = [
            [KeyboardButton("➕ 添加操作人"), KeyboardButton("➖ 删除操作人"), KeyboardButton("📋 操作人列表")],
            [KeyboardButton("🔄 更新操作人信息"), KeyboardButton("👥 临时操作人")],
            [KeyboardButton("◀️ 返回主菜单")],
        ]
    else:
        keyboard = [
            [KeyboardButton("👥 临时操作人")],
            [KeyboardButton("◀️ 返回主菜单")],
        ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_temp_operator_keyboard():
    """获取临时操作人键盘"""
    keyboard = [
        [KeyboardButton("➕ 添加临时操作人"), KeyboardButton("➖ 删除临时操作人"), KeyboardButton("📋 临时操作人列表")],
        [KeyboardButton("◀️ 返回操作人管理"), KeyboardButton("◀️ 返回主菜单")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_group_manager_keyboard():
    """获取群组管理键盘"""
    keyboard = [
        [KeyboardButton("📊 群组统计"), KeyboardButton("📁 查看分类"), KeyboardButton("➕ 创建分类")],
        [KeyboardButton("🏷️ 设置群组分类"), KeyboardButton("🗑️ 删除分类")],
        [KeyboardButton("◀️ 返回主菜单")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_transfer_keyboard():
    """获取互转查询键盘"""
    keyboard = [
        [KeyboardButton("🔍 转账查询"), KeyboardButton("🕸️ 转账分析")],
        [KeyboardButton("◀️ 返回主菜单")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_input_cancel_keyboard():
    """获取输入状态的键盘"""
    keyboard = [[KeyboardButton("◀️ 返回主菜单")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ==================== 已知按钮文本集合 ====================

ALL_KNOWN_BUTTONS = {
    # 主菜单
    "📒 记账", "🔔 USDT监控", "📢 群发", "💰 USDT查询",
    "👤 操作人管理", "🔄 互转查询", "📁 群组管理",
    # 监控
    "➕ 添加监控地址", "📋 监控列表", "📊 月度统计", "❌ 删除监控地址",
    # 操作人
    "➕ 添加操作人", "➖ 删除操作人", "📋 操作人列表", "🔄 更新操作人信息", "👥 临时操作人",
    # 临时操作人
    "➕ 添加临时操作人", "➖ 删除临时操作人", "📋 临时操作人列表",
    "◀️ 返回操作人管理",
    # 群组管理
    "📊 群组统计", "📁 查看分类", "➕ 创建分类", "🏷️ 设置群组分类", "🗑️ 删除分类",
    # 转账
    "🔍 转账查询", "🕸️ 转账分析",
    # 返回
    "◀️ 返回主菜单",
    "📖 使用说明", "👤 个人中心",
}


# ==================== 键盘处理器 (group=0) ====================

async def keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理固定键盘按钮点击 - group=0，最高优先级"""
    chat = update.effective_chat
    user_id = update.effective_user.id

    if chat.type != 'private':
        return

    text = update.message.text.strip()

    # ✅ 如果不是已知按钮，直接返回
    if text not in ALL_KNOWN_BUTTONS:
        return

    print(f"[KEYBOARD] 收到按钮: {text}")

    # ==================== 返回主菜单 ====================
    if text == "◀️ 返回主菜单":
        # 清除所有状态
        keys_to_clear = [
            "active_module", "usdt_session", "monitor_action", "monitor_temp",
            "current_action", "transfer_results", "current_page", "query_type",
            "in_broadcast", "selecting_group", "group_list", "filter_type",
            "selected_group_id",
        ]
        for key in keys_to_clear:
            context.user_data.pop(key, None)

        from handlers.group_manager import user_states
        if user_id in user_states:
            del user_states[user_id]

        await update.message.reply_text(
            "请选择功能：",
            reply_markup=get_main_menu(user_id)
        )
        return

    # ==================== 主菜单按钮 ====================
    if text == "📒 记账":
        context.user_data.clear()
        if not is_authorized(user_id, require_full_access=False):
            await update.message.reply_text("❌ 记账功能仅限管理员/操作员/临时操作员才能使用\n\n如需使用，请联系 @ChinaEdward 申请权限", reply_markup=get_main_menu(user_id))
            return
        await accounting.handle_keyboard(update, context)
        return

    elif text == "🔔 USDT监控":
        if not is_authorized(user_id, require_full_access=True):
            await update.message.reply_text("❌ 管理人/操作员才能使用，如需使用请联系 @ChinaEdward", reply_markup=get_main_menu(user_id))
            return
        await show_monitor_menu(update, context)
        return

    elif text == "📢 群发":
        if not is_authorized(user_id, require_full_access=True):
            await update.message.reply_text("❌ 管理人/操作员才能使用，如需使用请联系 @ChinaEdward", reply_markup=get_main_menu(user_id))
            return
        # 发送启动广播的内联按钮，让用户点击后进入广播流程
        keyboard = [
            [InlineKeyboardButton("🚀 开始设置群发", callback_data="broadcast")],
            [InlineKeyboardButton("◀️ 返回主菜单", callback_data="main_menu")],
        ]
        await update.message.reply_text(
            "📢 **群发消息**\n\n点击下方按钮开始设置群发内容。",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return

    elif text == "💰 USDT查询":
        if not is_authorized(user_id, require_full_access=True):
            await update.message.reply_text("❌ 管理人/操作员才能使用，如需使用请联系 @ChinaEdward", reply_markup=get_main_menu(user_id))
            return
        await start_usdt_query(update, context)
        return

    elif text == "👤 操作人管理":
        if not is_authorized(user_id, require_full_access=True):
            await update.message.reply_text("❌ 管理人/操作员才能使用，如需使用请联系 @ChinaEdward", reply_markup=get_main_menu(user_id))
            return
        await show_operator_menu(update, context)
        return

    elif text == "🔄 互转查询":
        if not is_authorized(user_id, require_full_access=True):
            await update.message.reply_text("❌ 管理人/操作员才能使用，如需使用请联系 @ChinaEdward", reply_markup=get_main_menu(user_id))
            return
        await show_transfer_menu(update, context)
        return

    elif text == "📁 群组管理":
        if not is_authorized(user_id, require_full_access=True):
            await update.message.reply_text("❌ 管理人/操作员才能使用，如需使用请联系 @ChinaEdward", reply_markup=get_main_menu(user_id))
            return
        await show_group_manager_menu(update, context)
        return

    elif text == "📖 使用说明":
        await handle_help(update, context)
        return

    elif text == "👤 个人中心":
        await handle_profile(update, context)
        return

    # ==================== USDT 监控子菜单 ====================
    elif text == "➕ 添加监控地址":
        if not is_authorized(user_id, require_full_access=True):
            await update.message.reply_text("❌ 无权限", reply_markup=get_main_menu(user_id))
            return
        context.user_data["monitor_action"] = "add"
        await update.message.reply_text(
            "➕ 添加监控地址\n\n请输入要监控的 USDT 地址：\n\n支持格式：\n• TRC20: T 开头，34位\n• ERC20: 0x 开头，42位\n\n❌ 点击「返回主菜单」取消",
            reply_markup=get_input_cancel_keyboard()
        )
        return

    elif text == "📋 监控列表":
        if not is_authorized(user_id, require_full_access=True):
            await update.message.reply_text("❌ 无权限", reply_markup=get_main_menu(user_id))
            return
        addresses = get_monitored_addresses(user_id=user_id)
        if not addresses:
            await update.message.reply_text("📭 您还没有添加任何监控地址", reply_markup=get_monitor_keyboard(user_id))
            return
        text_msg = "📋 **您的监控地址列表**\n\n"
        for i, addr_info in enumerate(addresses, 1):
            full_addr = addr_info['address']
            note = addr_info.get('note', '')
            text_msg += f"{i}. `{full_addr}` ({addr_info['chain_type']})\n"
            if note:
                text_msg += f"   📝 备注：{note}\n"
            text_msg += "\n"
        await update.message.reply_text(text_msg, reply_markup=get_monitor_keyboard(user_id), parse_mode=None)
        return

    elif text == "📊 月度统计":
        if not is_authorized(user_id, require_full_access=True):
            await update.message.reply_text("❌ 无权限", reply_markup=get_main_menu(user_id))
            return
        addresses = get_monitored_addresses(user_id=user_id)
        if not addresses:
            await update.message.reply_text("📭 您还没有添加任何监控地址", reply_markup=get_monitor_keyboard(user_id))
            return
        temp_msg = await update.message.reply_text("📊 正在查询月度统计，请稍候...")
        text_msg = "📊 **监控地址月度统计**\n\n"
        for addr_info in addresses:
            address = addr_info["address"]
            note = addr_info.get("note", "")
            short_addr = f"{address[:8]}...{address[-6:]}"
            stats = await monitor.get_monthly_stats(address)
            text_msg += f"📌 {short_addr}"
            if note:
                text_msg += f" ({note})"
            text_msg += f"\n   💰 本月收到：**{stats['received']:.2f} USDT**"
            text_msg += f"\n   📤 本月转出：**{stats['sent']:.2f} USDT**"
            text_msg += f"\n   📈 净收入：**{stats['net']:.2f} USDT**\n\n"
        await temp_msg.edit_text(text_msg, parse_mode=None)
        await update.message.reply_text("选择操作：", reply_markup=get_monitor_keyboard(user_id))
        return

    elif text == "❌ 删除监控地址":
        if not is_authorized(user_id, require_full_access=True):
            await update.message.reply_text("❌ 无权限", reply_markup=get_main_menu(user_id))
            return
        addresses = get_monitored_addresses(user_id=user_id)
        if not addresses:
            await update.message.reply_text("📭 您还没有添加任何监控地址", reply_markup=get_monitor_keyboard(user_id))
            return
        keyboard = []
        for addr in addresses:
            full_addr = addr['address']
            note = addr.get('note', '')
            short_addr = f"{full_addr[:12]}...{full_addr[-8:]}"
            button_text = f"🗑️ {short_addr} ({note})" if note else f"🗑️ {short_addr}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"monitor_del_{addr['id']}")])

        await update.message.reply_text(
            "🗑️ **删除监控地址**\n\n选择要删除的地址：\n\n💡 点击「返回主菜单」取消",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ==================== 操作人管理子菜单 ====================
    elif text == "➕ 添加操作人":
        from config import OWNER_ID
        if user_id != OWNER_ID:
            await update.message.reply_text("❌ 只有控制人可以管理正式操作人", reply_markup=get_main_menu(user_id))
            return
        context.user_data["current_action"] = operator.ADD_OPERATOR
        context.user_data["active_module"] = "operator"
        await update.message.reply_text("请输入要添加的用户ID（纯数字）：", reply_markup=get_input_cancel_keyboard())
        return

    elif text == "➖ 删除操作人":
        from config import OWNER_ID
        if user_id != OWNER_ID:
            await update.message.reply_text("❌ 只有控制人可以管理正式操作人", reply_markup=get_main_menu(user_id))
            return
        context.user_data["current_action"] = operator.REMOVE_OPERATOR
        context.user_data["active_module"] = "operator"
        await update.message.reply_text("请输入要删除的用户ID（纯数字）：", reply_markup=get_input_cancel_keyboard())
        return

    elif text == "📋 操作人列表":
        from config import OWNER_ID
        if user_id != OWNER_ID:
            await update.message.reply_text("❌ 只有控制人可以管理正式操作人", reply_markup=get_main_menu(user_id))
            return
        from auth import get_operators_list_text
        text_msg = get_operators_list_text()
        await update.message.reply_text(text_msg, parse_mode="Markdown", reply_markup=get_operator_keyboard(user_id))
        return

    elif text == "🔄 更新操作人信息":
        from config import OWNER_ID
        if user_id != OWNER_ID:
            await update.message.reply_text("❌ 只有控制人可以管理正式操作人", reply_markup=get_main_menu(user_id))
            return
        await update.message.reply_text("🔄 正在更新操作人信息，请稍候...")
        from auth import update_all_operators_info
        count = await update_all_operators_info(context)
        if count > 0:
            await update.message.reply_text(f"✅ 已成功更新 {count} 个操作人的信息", reply_markup=get_operator_keyboard(user_id))
        else:
            await update.message.reply_text("⚠️ 没有操作人被更新，或更新失败", reply_markup=get_operator_keyboard(user_id))
        return

    elif text == "👥 临时操作人":
        await update.message.reply_text(
            "👥 **临时操作人管理**\n\n临时操作人**只能使用记账功能**\n\n请选择操作：",
            reply_markup=get_temp_operator_keyboard(),
            parse_mode="Markdown"
        )
        return

    elif text == "➕ 添加临时操作人":
        context.user_data["current_action"] = operator.ADD_TEMP_OPERATOR
        context.user_data["active_module"] = "operator"
        await update.message.reply_text("请输入要添加的**临时操作人**ID（纯数字）：\n\n💡 临时操作人只能使用记账功能", reply_markup=get_input_cancel_keyboard())
        return

    elif text == "➖ 删除临时操作人":
        context.user_data["current_action"] = operator.REMOVE_TEMP_OPERATOR
        context.user_data["active_module"] = "operator"
        await update.message.reply_text("请输入要删除的**临时操作人**ID（纯数字）：", reply_markup=get_input_cancel_keyboard())
        return

    elif text == "📋 临时操作人列表":
        from auth import get_temp_operators_list_text
        text_msg = get_temp_operators_list_text()
        await update.message.reply_text(text_msg, parse_mode="Markdown", reply_markup=get_temp_operator_keyboard())
        return

    elif text == "◀️ 返回操作人管理":
        await show_operator_menu(update, context)
        return

    # ==================== 群组管理子菜单 ====================
    elif text == "📊 群组统计":
        if not is_authorized(user_id, require_full_access=True):
            await update.message.reply_text("❌ 无权限", reply_markup=get_main_menu(user_id))
            return
        from db import get_groups_by_category, get_all_categories
        groups_by_cat = get_groups_by_category()
        categories = get_all_categories()
        text_msg = "📊 **群组统计**\n\n"
        for cat in categories:
            cat_name = cat['name']
            count = groups_by_cat.get(cat_name, 0)
            text_msg += f"• **{cat_name}**：{count} 个群组\n"
        text_msg += f"\n总计：**{sum(groups_by_cat.values())}** 个群组"
        await update.message.reply_text(text_msg, parse_mode="Markdown", reply_markup=get_group_manager_keyboard())
        return

    elif text == "📁 查看分类":
        if not is_authorized(user_id, require_full_access=True):
            await update.message.reply_text("❌ 无权限", reply_markup=get_main_menu(user_id))
            return
        from db import get_all_categories, get_groups_by_category
        categories = get_all_categories()
        groups_by_cat = get_groups_by_category()
        text_msg = "📁 **现有分类**\n\n"
        for cat in categories:
            cat_name = cat['name']
            count = groups_by_cat.get(cat_name, 0)
            text_msg += f"• **{cat_name}** ({count}个群组)\n"
        await update.message.reply_text(text_msg, parse_mode="Markdown", reply_markup=get_group_manager_keyboard())
        return

    elif text == "➕ 创建分类":
        if not is_authorized(user_id, require_full_access=True):
            await update.message.reply_text("❌ 无权限", reply_markup=get_main_menu(user_id))
            return
        from handlers.group_manager import user_states
        user_states[user_id] = {"action": "add_category_name", "timestamp": asyncio.get_event_loop().time()}
        await update.message.reply_text(
            "➕ **创建新分类**\n\n请输入分类名称（如：VIP群组）：\n\n❌ 点击「返回主菜单」取消",
            parse_mode="Markdown",
            reply_markup=get_input_cancel_keyboard()
        )
        return

    elif text == "🏷️ 设置群组分类":
        if not is_authorized(user_id, require_full_access=True):
            await update.message.reply_text("❌ 无权限", reply_markup=get_main_menu(user_id))
            return
        from db import get_all_groups_from_db
        groups = get_all_groups_from_db()
        if not groups:
            await update.message.reply_text("📭 暂无群组", reply_markup=get_group_manager_keyboard())
            return
        context.user_data['group_list'] = groups
        context.user_data['current_page'] = 0
        await show_group_list_inline(update, context)
        return

    elif text == "🗑️ 删除分类":
        if not is_authorized(user_id, require_full_access=True):
            await update.message.reply_text("❌ 无权限", reply_markup=get_main_menu(user_id))
            return
        from db import get_all_categories
        categories = get_all_categories()
        deletable = [cat for cat in categories if cat['name'] != '未分类']
        if not deletable:
            await update.message.reply_text("⚠️ 没有可删除的分类（「未分类」不能删除）", reply_markup=get_group_manager_keyboard())
            return
        # 存储到上下文，启用分页
        context.user_data["del_categories"] = deletable
        context.user_data["del_categories_page"] = 0
        # 调用分页显示函数（非回调模式）
        from handlers.group_manager import send_delete_category_page
        await send_delete_category_page(update, context, is_callback=False)
        return

    # ==================== 互转查询子菜单 ====================
    elif text == "🔍 转账查询":
        if not is_authorized(user_id, require_full_access=True):
            await update.message.reply_text("❌ 无权限", reply_markup=get_main_menu(user_id))
            return
        context.user_data.pop("transfer_results", None)
        context.user_data.pop("current_page", None)
        context.user_data.pop("query_type", None)
        context.user_data["active_module"] = "transfer_query"
        await update.message.reply_text(
            "🔍 **转账查询**\n\n请输入两个 USDT 地址，中间用空格隔开：\n例如：`Txxxx... Tyyyy...`",
            parse_mode="Markdown",
            reply_markup=get_input_cancel_keyboard()
        )
        return

    elif text == "🕸️ 转账分析":
        if not is_authorized(user_id, require_full_access=True):
            await update.message.reply_text("❌ 无权限", reply_markup=get_main_menu(user_id))
            return
        context.user_data.pop("transfer_results", None)
        context.user_data.pop("current_page", None)
        context.user_data.pop("query_type", None)
        context.user_data["active_module"] = "transfer_analysis"
        await update.message.reply_text(
            "🕵️ **转账分析**\n\n将分析是否有第三方地址与这两个地址都产生过交易。\n请输入两个 USDT 地址，中间用空格隔开：\n例如：`Txxxx... Tyyyy...`",
            parse_mode="Markdown",
            reply_markup=get_input_cancel_keyboard()
        )
        return


# ==================== 模块输入处理器 (group=1) ====================
async def module_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理各模块的输入状态 - group=1"""
    chat = update.effective_chat
    user_id = update.effective_user.id

    if chat.type != 'private':
        return

    # 检查个人中心输入标志，有则拦截并清除标志
    if context.user_data.pop("profile_input_state", False):
        return ConversationHandler.END

    text = update.message.text.strip() if update.message.text else ""

    # 如果是已知键盘按钮，不处理
    if text in ALL_KNOWN_BUTTONS:
        return

    # 1. 检查群组管理状态
    from handlers.group_manager import user_states
    if user_id in user_states:
        from handlers.group_manager import handle_text_input
        await handle_text_input(update, context)
        context.user_data["_message_handled"] = True
        return ConversationHandler.END

    # 2. 检查监控模块状态 (关键修复)
    monitor_action = context.user_data.get("monitor_action")
    if monitor_action == "add":
        await monitor.monitor_add_input(update, context)
        context.user_data["_message_handled"] = True
        return ConversationHandler.END # 强制终止
    elif monitor_action == "add_note":
        await monitor.monitor_add_note(update, context)
        context.user_data["_message_handled"] = True
        return ConversationHandler.END # 强制终止

    # 3. 检查操作员管理状态
    current_action = context.user_data.get("current_action")
    if current_action in [operator.ADD_OPERATOR, operator.REMOVE_OPERATOR, 
                           operator.ADD_TEMP_OPERATOR, operator.REMOVE_TEMP_OPERATOR]:
        await operator.handle_input(update, context)
        context.user_data["_message_handled"] = True
        return ConversationHandler.END # 强制终止

    # 4. 检查 USDT 地址查询状态
    usdt_session = context.user_data.get("usdt_session")
    if usdt_session and usdt_session.get("waiting_for_address"):
        try:
            await usdt.handle_input(update, context)
        except Exception as e:
            context.user_data.pop("active_module", None)
            context.user_data.pop("usdt_session", None)
            await update.message.reply_text("❌ USDT 查询出错，请重试")
        context.user_data["_message_handled"] = True
        return ConversationHandler.END

    # 5. 检查互转查询状态
    active_module = context.user_data.get("active_module")
    if active_module == "transfer_query":
        await handle_transfer_query_input(update, context)
        context.user_data["_message_handled"] = True
        return ConversationHandler.END
    elif active_module == "transfer_analysis":
        await handle_transfer_analysis_input(update, context)
        context.user_data["_message_handled"] = True
        return ConversationHandler.END

    # 6. 检查广播模块状态
    if context.user_data.get("in_broadcast", False):
        context.user_data["_message_handled"] = True
        return ConversationHandler.END

    # 不是任何模块的输入，返回 None 让 ai_chat_handler 处理
    return None


# ==================== AI 对话处理器 (group=2) ====================

async def ai_chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 AI 对话 - group=2，最低优先级"""
    chat = update.effective_chat
    user_id = update.effective_user.id

    if chat.type != 'private':
        return

    # 检查个人中心输入标志，有则拦截并清除标志
    if context.user_data.pop("profile_input_state", False):
        return

    # ✅ 终极防御：如果消息已被其他模块处理，绝对不进入 AI
    if context.user_data.get("_message_handled"):
        context.user_data.pop("_message_handled", None) # 清理标记
        return
        
    text = update.message.text.strip() if update.message.text else ""

    if text in ALL_KNOWN_BUTTONS or text.startswith('/'):
        return

    # ✅ 只要存在任何模块状态，就不进入 AI 对话
    if any([
        context.user_data.get("active_module"),
        context.user_data.get("monitor_action"),
        context.user_data.get("current_action"),
        context.user_data.get("in_broadcast"),
        context.user_data.get("usdt_session"),
        context.user_data.get("transfer_results"),
        context.user_data.get("selecting_group"),
    ]):
        return

    from handlers.group_manager import user_states
    if user_id in user_states:
        return

    # 检查互转查询地址格式
    import re
    if re.match(r'^T[0-9A-Za-z]{33}\s+T[0-9A-Za-z]{33}$', text):
        return

    if not text:
        return

    print(f"[AI_CHAT] 进入 AI 对话: {text[:50]}")

    if not is_authorized(user_id, require_full_access=True):
        await update.message.reply_text("❌ AI 对话功能仅限管理员和操作员使用\n\n如需使用，请联系 @ChinaEdward 申请权限")
        return

    thinking_msg = await update.message.reply_text("🤔 思考中...")

    try:
        ai_client = get_ai_client()
        reply = await ai_client.chat_with_data(text, user_id=user_id)
        if len(reply) > 4000:
            reply = reply[:4000] + "...\n\n(回复过长已截断)"
        await thinking_msg.edit_text(reply)
    except Exception as e:
        print(f"[DEBUG] AI 调用失败: {e}")
        await thinking_msg.edit_text(f"❌ AI 服务出错: {str(e)[:100]}")


# ==================== 菜单显示函数 ====================
async def show_monitor_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    addresses = get_monitored_addresses(user_id=user_id)
    if len(addresses) == 0:
        text = "🔔 USDT 地址监控\n\n📊 您的监控地址数：0 个\n\n⚠️ 暂无监控地址，请先添加。\n\n💡 支持为地址添加备注"
    else:
        text = f"🔔 USDT 地址监控\n\n📊 您的监控地址数：{len(addresses)} 个\n\n当监控地址有交易时，会发送通知。\n\n💡 监控间隔约 30 秒"
    await update.message.reply_text(text, reply_markup=monitor.get_monitor_keyboard_markup(user_id), parse_mode=None)

async def show_operator_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示操作人管理菜单"""
    user_id = update.effective_user.id
    await update.message.reply_text("👤 操作人管理：请选择功能", reply_markup=get_operator_keyboard(user_id))


async def show_transfer_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示互转查询菜单"""
    context.user_data.pop("transfer_results", None)
    context.user_data.pop("current_page", None)
    context.user_data.pop("query_type", None)
    context.user_data.pop("active_module", None)
    await update.message.reply_text("💱 **互转查询功能**\n请选择操作：", reply_markup=get_transfer_keyboard(), parse_mode="Markdown")


async def show_group_manager_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示群组管理菜单"""
    from db import get_all_categories, get_groups_by_category
    categories = get_all_categories()
    groups_by_cat = get_groups_by_category()
    total_groups = sum(groups_by_cat.values())
    text = f"📁 **群组分类管理**\n\n📊 总群组数：**{total_groups}** 个\n🏷️ 分类数量：**{len(categories)}** 个\n\n💡 点击下方按钮进行操作"
    await update.message.reply_text(text, reply_markup=get_group_manager_keyboard(), parse_mode="Markdown")


async def start_usdt_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始 USDT 查询"""
    context.user_data["active_module"] = "usdt"
    context.user_data["usdt_session"] = {"waiting_for_address": True}
    await update.message.reply_text("💰 请输入 TRON TRC20 地址（T 开头）：", reply_markup=get_input_cancel_keyboard())


async def start_broadcast_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始群发流程"""
    user_id = update.effective_user.id
    context.user_data["in_broadcast"] = True

    keys = ["bc_all_groups", "bc_selected_ids", "bc_message_content", "bc_temp_target_ids",
            "bc_selected_category", "bc_batches", "bc_current_batch", "bc_batch_results",
            "bc_waiting_for_next", "bc_current_state", "bc_current_page"]
    for k in keys:
        context.user_data.pop(k, None)

    from db import get_all_groups_from_db
    groups = get_all_groups_from_db()

    if not groups:
        await update.message.reply_text("⚠️ **未找到任何有效群组**\n\n请确保机器人已添加到群组中。", reply_markup=get_main_menu(user_id))
        return

    context.user_data["bc_all_groups"] = groups
    context.user_data["bc_selected_ids"] = []

    # 使用内联按钮显示群组选择
    await broadcast.show_group_selection(update, context)


# ==================== 互转查询输入处理 ====================

async def handle_transfer_query_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理转账查询输入"""
    text = update.message.text.strip()
    parts = text.split()

    if len(parts) != 2:
        await update.message.reply_text("❌ 格式错误，请输入两个地址，用空格隔开。", reply_markup=get_input_cancel_keyboard())
        return

    addr_a, addr_b = parts[0], parts[1]

    if not (addr_a.startswith('T') and addr_b.startswith('T')) or len(addr_a) != 34 or len(addr_b) != 34:
        await update.message.reply_text("❌ 地址格式不正确 (Tron 地址以 T 开头，长度 34)。", reply_markup=get_input_cancel_keyboard())
        return

    await update.message.reply_text("⏳ 正在查询链上数据，请稍候...")

    from handlers.transfer import get_trc20_transfers

    history_a = get_trc20_transfers(addr_a, limit=200)
    history_b = get_trc20_transfers(addr_b, limit=200)

    matches = []
    for tx in history_a:
        if tx.get("to") == addr_b or tx.get("from") == addr_b:
            matches.append(tx)

    seen_tx_ids = set()
    unique_matches = []
    for tx in matches:
        tx_id = tx.get("txID") or tx.get("transaction_id")
        if tx_id not in seen_tx_ids:
            seen_tx_ids.add(tx_id)
            unique_matches.append(tx)

    if not unique_matches:
        for tx in history_b:
            if tx.get("to") == addr_a or tx.get("from") == addr_a:
                tx_id = tx.get("txID") or tx.get("transaction_id")
                if tx_id not in seen_tx_ids:
                    unique_matches.append(tx)

    if not unique_matches:
        await update.message.reply_text("📭 未找到直接转账记录。", reply_markup=get_transfer_keyboard())
        context.user_data.pop("active_module", None)
        return

    # 显示结果（使用内联分页按钮）
    context.user_data["transfer_results"] = unique_matches
    context.user_data["current_page"] = 0
    context.user_data["query_type"] = "direct"
    context.user_data["active_module"] = "transfer_result"

    await send_transfer_page(update, context, 0)


async def handle_transfer_analysis_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理转账分析输入"""
    text = update.message.text.strip()
    parts = text.split()

    if len(parts) != 2:
        await update.message.reply_text("❌ 格式错误，请输入两个地址，用空格隔开。", reply_markup=get_input_cancel_keyboard())
        return

    addr_a, addr_b = parts[0], parts[1]

    if not (addr_a.startswith('T') and addr_b.startswith('T')) or len(addr_a) != 34 or len(addr_b) != 34:
        await update.message.reply_text("❌ 地址格式不正确。", reply_markup=get_input_cancel_keyboard())
        return

    await update.message.reply_text("⏳ 正在深度分析链上关系，这可能需要一点时间...")

    from handlers.transfer import get_trc20_transfers, extract_counterparties

    history_a = get_trc20_transfers(addr_a, limit=200)
    history_b = get_trc20_transfers(addr_b, limit=200)

    set_a = extract_counterparties(history_a, addr_a)
    set_b = extract_counterparties(history_b, addr_b)

    common_parties = list(set_a.intersection(set_b))
    common_parties = [p for p in common_parties if p != addr_a and p != addr_b]

    if not common_parties:
        await update.message.reply_text("📭 未发现共同交易对手。", reply_markup=get_transfer_keyboard())
        context.user_data.pop("active_module", None)
        return

    context.user_data["transfer_results"] = common_parties
    context.user_data["current_page"] = 0
    context.user_data["query_type"] = "analysis"
    context.user_data["active_module"] = "transfer_result"

    await send_transfer_page(update, context, 0)


async def send_transfer_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page_num: int):
    """发送转账结果分页"""
    # 兼容两种触发方式：消息触发 / 回调触发
    if update.callback_query:
        query = update.callback_query
        chat_id = query.message.chat_id
        reply_msg = query.message          # 用来回复或编辑
    else:
        chat_id = update.effective_chat.id
        reply_msg = update.message

    results = context.user_data.get("transfer_results", [])
    query_type = context.user_data.get("query_type")

    if not results:
        return

    page_size = 5
    total_pages = (len(results) + page_size - 1) // page_size
    start_idx = page_num * page_size
    end_idx = min(start_idx + page_size, len(results))
    current_items = results[start_idx:end_idx]

    text = ""
    keyboard = []

    if query_type == "direct":
        text = f"🔗 **直接转账记录** (第 {page_num+1}/{total_pages} 页)\n\n"
        for i, tx in enumerate(current_items, start=start_idx):
            raw_amount = tx.get("value") or tx.get("amount") or 0
            try:
                amount_float = float(str(raw_amount)) / 1_000_000.0
            except:
                amount_float = 0.0

            amount_str = f"{amount_float:.2f}"
            from_addr = tx.get("from", "Unknown")
            to_addr = tx.get("to", "Unknown")
            from_short = f"{from_addr[:6]}...{from_addr[-6:]}" if len(from_addr) >= 12 else from_addr
            to_short = f"{to_addr[:6]}...{to_addr[-6:]}" if len(to_addr) >= 12 else to_addr

            text += f"{i+1}. 💰 **{amount_str} USDT**\n"
            text += f"   🟢 {from_short} ➡️ 🔴 {to_short}\n"

            timestamp = tx.get("block_timestamp", 0)
            if timestamp:
                from datetime import datetime
                dt = datetime.fromtimestamp(timestamp / 1000)
                text += f"   ⏰ {dt.strftime('%Y-%m-%d %H:%M:%S')}\n"

            tx_id = tx.get("txID") or tx.get("transaction_id", "")
            if tx_id:
                text += f"   🔗 [查看详情](https://tronscan.org/#/transaction/{tx_id})\n"
            text += "\n"

    elif query_type == "analysis":
        text = f"🕸️ **共同交易对手地址** (第 {page_num+1}/{total_pages} 页)\n\n"
        text += "以下地址同时与您查询的两个地址有过交易：\n\n"
        for i, addr in enumerate(current_items, start=start_idx):
            short_addr = addr[:8] + "..." + addr[-6:]
            text += f"{i+1}. `{addr}`\n   ({short_addr})\n\n"
            keyboard.append([InlineKeyboardButton(f"📋 复制地址 {i+1}", callback_data=f"copy_addr_{addr}")])

    # 分页按钮
    nav_buttons = []
    if page_num > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"trans_page_{page_num-1}"))
    if page_num < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"trans_page_{page_num+1}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    # 如果是通过内联按钮触发（回调），则编辑原消息；否则发送新消息
    if update.callback_query:
        try:
            await query.message.edit_text(
                text,
                parse_mode="Markdown",
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
        except Exception:
            # 编辑失败就发送新消息
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
    else:
        await reply_msg.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
        # 去掉原来多余的返回按钮提示，改为在结果内联键盘中提供返回主菜单（可选）
    
# ==================== 群组列表内联显示 ====================

async def show_group_list_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示群组列表（内联按钮版）"""
    groups = context.user_data.get('group_list', [])
    current_page = context.user_data.get('current_page', 0)

    # 确定消息对象
    if update.callback_query:
        message = update.callback_query.message
    else:
        message = update.message

    if not groups:
        await message.reply_text("📭 暂无群组", reply_markup=get_group_manager_keyboard())
        return

    ITEMS_PER_PAGE = 8
    total_pages = (len(groups) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start_idx = current_page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(groups))
    current_groups = groups[start_idx:end_idx]

    keyboard = []

    # 筛选按钮
    keyboard.append([
        InlineKeyboardButton("📋 未分类", callback_data="filter_uncategorized"),
        InlineKeyboardButton("✅ 已分类", callback_data="filter_categorized")
    ])

    # 群组列表
    for group in current_groups:
        title = group['title'][:25]
        current_cat = group.get('category', '未分类')
        keyboard.append([InlineKeyboardButton(
            f"{title} (当前: {current_cat})", 
            callback_data=f"sel_group_{group['id']}"
        )])

    # 分页按钮
    nav_buttons = []
    if current_page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data="group_page_prev"))
    if current_page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data="group_page_next"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("🔄 刷新列表", callback_data="refresh_group_list")])

    text = f"🏷️ **设置群组分类**\n\n请选择要设置分类的群组：\n共 **{len(groups)}** 个群组，第 **{current_page + 1}/{total_pages}** 页\n\n💡 点击「返回主菜单」取消"

    reply_markup = InlineKeyboardMarkup(keyboard)

    # 优先尝试编辑消息（无闪烁）
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode=None
            )
        else:
            await message.reply_text(text, reply_markup=reply_markup, parse_mode=None)
    except Exception as e:
        # 编辑失败（可能是消息内容问题），回退到删除原消息并发送新消息
        print(f"编辑消息失败，回退到删除重发: {e}")
        try:
            if update.callback_query:
                await update.callback_query.message.delete()
        except Exception:
            pass
        await message.reply_text(text, reply_markup=reply_markup, parse_mode=None)


# ==================== 内联按钮路由处理器 ====================

async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理所有内联按钮回调"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    data = query.data
    print(f"[BUTTON_ROUTER] 收到: {data}")

    if data.startswith("profile_"):
        return

    # ========== 转账分页 ==========
    if data.startswith("trans_page_"):
        page_num = int(data.split("_")[2])
        await send_transfer_page(update, context, page_num)
        return

    if data.startswith("copy_addr_"):
        addr = data.replace("copy_addr_", "")
        await query.message.reply_text(f"📋 已获取地址：\n<code>{addr}</code>", parse_mode="HTML")
        return

    # 放在 button_router 函数内，例如在“转账分页”处理之后
    if data == "main_menu":
        # 清除广播及其他可能的状态
        keys_to_clean = [
            "in_broadcast", "bc_all_groups", "bc_selected_ids", "bc_message_content",
            "bc_temp_target_ids", "bc_selected_category", "bc_batches", "bc_current_batch",
            "bc_batch_results", "bc_waiting_for_next", "bc_current_state", "bc_current_page",
            "active_module", "transfer_results", "current_page", "query_type"
        ]
        for k in keys_to_clean:
            context.user_data.pop(k, None)

        from handlers.menu import get_main_menu
        # 尝试编辑原消息，若失败则发送新消息
        try:
            await query.message.edit_text("请选择功能：", reply_markup=get_main_menu(user_id))
        except Exception:
            await query.message.reply_text("请选择功能：", reply_markup=get_main_menu(user_id))
        return  # 或 return ConversationHandler.END（此处无关紧要）

    # ========== 监控模块 ==========
    if data.startswith("monitor_del_"):
        await monitor.monitor_remove_confirm(update, context)
        return

    # ========== 群组管理菜单 ==========
    if data == "group_manager":
        from handlers.group_manager import group_manager_menu
        await group_manager_menu(update, context)
        return

    if data == "gm_stats":
        from handlers.group_manager import show_stats
        await show_stats(update, context)
        return

    if data == "gm_list_cats":
        from handlers.group_manager import list_categories
        await list_categories(update, context)
        return

    if data == "gm_add_cat":
        from handlers.group_manager import add_category_start
        await add_category_start(update, context)
        return

    if data == "gm_set_cat":
        from handlers.group_manager import set_group_category_start
        await set_group_category_start(update, context)
        return

    if data == "gm_del_cat":
        from handlers.group_manager import delete_category_start
        await delete_category_start(update, context)
        return
        
    # ========== 群组分类选择 ==========
    if data.startswith("sel_group_"):
        await select_group_for_category(update, context)
        return

    # 设置分类时的分页按钮（必须先检查）
    if data in ("set_cat_page_prev", "set_cat_page_next"):
        from handlers.group_manager import handle_set_category_pagination
        await handle_set_category_pagination(update, context)
        return

    # 设置分类
    if data.startswith("set_cat_"):
        await set_group_category(update, context)
        return

    # 删除分类的分页按钮（必须先检查）
    if data in ("del_cat_page_prev", "del_cat_page_next"):
        from handlers.group_manager import handle_delete_category_pagination
        await handle_delete_category_pagination(update, context)
        return

    # 删除分类确认
    if data.startswith("del_cat_"):
        await delete_category_confirm(update, context)
        return

    # ========== 群组列表分页和筛选 ==========
    if data == "group_page_prev":
        current_page = context.user_data.get('current_page', 0)
        context.user_data['current_page'] = max(0, current_page - 1)
        await show_group_list_inline(update, context)
        return

    if data == "group_page_next":
        current_page = context.user_data.get('current_page', 0)
        groups = context.user_data.get('group_list', [])
        ITEMS_PER_PAGE = 8
        total_pages = (len(groups) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        context.user_data['current_page'] = min(total_pages - 1, current_page + 1)
        await show_group_list_inline(update, context)
        return

    if data == "refresh_group_list":
        from db import get_all_groups_from_db
        groups = get_all_groups_from_db()
        context.user_data['group_list'] = groups
        context.user_data['current_page'] = 0
        context.user_data.pop('filter_type', None)
        await show_group_list_inline(update, context)
        return

    if data == "filter_uncategorized":
        from db import get_all_groups_from_db
        all_groups = get_all_groups_from_db()
        filtered = [g for g in all_groups if g.get('category', '未分类') == '未分类']
        if not filtered:
            await query.message.edit_text("📭 暂无未分类的群组")
            await asyncio.sleep(1)
            context.user_data['group_list'] = all_groups
            context.user_data['current_page'] = 0
            await show_group_list_inline(update, context)
            return
        context.user_data['group_list'] = filtered
        context.user_data['current_page'] = 0
        context.user_data['filter_type'] = 'uncategorized'
        await show_group_list_inline(update, context)
        return

    if data == "filter_categorized":
        from db import get_all_groups_from_db
        all_groups = get_all_groups_from_db()
        filtered = [g for g in all_groups if g.get('category', '未分类') != '未分类']
        if not filtered:
            await query.message.edit_text("📭 暂无已分类的群组")
            await asyncio.sleep(1)
            context.user_data['group_list'] = all_groups
            context.user_data['current_page'] = 0
            await show_group_list_inline(update, context)
            return
        context.user_data['group_list'] = filtered
        context.user_data['current_page'] = 0
        context.user_data['filter_type'] = 'categorized'
        await show_group_list_inline(update, context)
        return

    # ========== USDT 分页 ==========
    if data.startswith("usdt_"):
        await usdt.handle_buttons(update, context)
        return

    # ========== 账单分页 ==========
    if data.startswith("bill_page_"):
        from handlers.accounting import handle_bill_pagination
        await handle_bill_pagination(update, context)
        return

    if data == "bill_close":
        from handlers.accounting import handle_bill_pagination
        await handle_bill_pagination(update, context)
        return

    # ========== 记账日期选择 ==========
    if data.startswith("bill_year_"):
        from handlers.accounting import handle_year_selection
        await handle_year_selection(update, context)
        return

    if data.startswith("bill_month_"):
        from handlers.accounting import handle_month_selection
        await handle_month_selection(update, context)
        return

    if data.startswith("bill_day_"):
        from handlers.accounting import handle_day_selection
        await handle_day_selection(update, context)
        return

    if data in ["bill_back_to_years", "bill_back_to_months", "bill_days_prev", "bill_days_next"]:
        from handlers.accounting import handle_bill_navigation
        await handle_bill_navigation(update, context)
        return

    # ========== 导出账单 ==========
    if data.startswith("export_full_year_"):
        from handlers.accounting import handle_export_month_selection
        await handle_export_month_selection(update, context)
        return
        
    if data.startswith("export_year_"):
        from handlers.accounting import handle_export_year_selection
        await handle_export_year_selection(update, context)
        return

    if data.startswith("export_month_"):
        from handlers.accounting import handle_export_month_selection
        await handle_export_month_selection(update, context)
        return

    if data.startswith("export_day_") or data.startswith("export_full_month_") or data in ["export_days_prev", "export_days_next", "export_back_to_months"]:
        from handlers.accounting import handle_export_day_selection
        await handle_export_day_selection(update, context)
        return

    if data == "export_cancel":
        await query.message.edit_text("✅ 已取消导出")
        return

    # ========== 清理确认 ==========
    if data in ["clear_current_confirm", "clear_current_cancel", "clear_all_confirm", "clear_all_cancel"]:
        from handlers.accounting import (
            handle_clear_current_confirm, handle_clear_current_cancel,
            handle_clear_all_confirm, handle_clear_all_cancel
        )
        if data == "clear_current_confirm":
            await handle_clear_current_confirm(update, context)
        elif data == "clear_current_cancel":
            await handle_clear_current_cancel(update, context)
        elif data == "clear_all_confirm":
            await handle_clear_all_confirm(update, context)
        elif data == "clear_all_cancel":
            await handle_clear_all_cancel(update, context)
        return

    if data.startswith("acct_date_"):
        from handlers.accounting import handle_date_selection
        await handle_date_selection(update, context)
        return

    if data == "acct_cancel":
        await query.message.edit_text("✅ 已取消")
        return

    print(f"[BUTTON_ROUTER] 未处理: {data}")


# ==================== 原有函数保留 ====================

async def auto_save_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat and update.effective_chat.type in ['group', 'supergroup']:
        chat_id = str(update.effective_chat.id)
        title = update.effective_chat.title
        try:
            bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
            if bot_member.status not in ['member', 'administrator']:
                return
        except:
            return
        from db import get_all_groups_from_db
        existing_groups = get_all_groups_from_db()
        existing = next((g for g in existing_groups if g['id'] == chat_id), None)
        category = existing['category'] if existing else '未分类'
        save_group(chat_id, title, category)
        from db import update_group_category_if_needed


async def auto_classify_all_groups_on_startup(app: Application):
    from db import get_all_groups_from_db, update_group_category_if_needed
    await asyncio.sleep(3)
    groups = get_all_groups_from_db()
    classified_count = 0
    for group in groups:
        if group.get('category', '未分类') == '未分类':
            if update_group_category_if_needed(group['id'], group['title']):
                classified_count += 1
    print(f"[自动分类] 完成！自动分类了 {classified_count} 个群组")


async def on_bot_join_or_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    my_chat_member = update.my_chat_member
    chat = my_chat_member.chat
    new_status = my_chat_member.new_chat_member.status
    chat_id = str(chat.id)
    title = chat.title
    if new_status in ['member', 'administrator']:
        save_group(chat_id, title, '未分类')
    elif new_status in ['left', 'kicked', 'banned']:
        delete_group_from_db(chat_id)
        await asyncio.sleep(1)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    from handlers.group_manager import user_states, handle_cancel_in_group_manager
    if user_id in user_states:
        await handle_cancel_in_group_manager(update, context)
        return
    if context.user_data.get("in_broadcast", False):
        return
    context.user_data.clear()
    await update.message.reply_text("❌ 已取消所有操作")

async def send_daily_reports(app: Application):
    import sqlite3
    from auth import is_authorized, OWNER_ID
    from db import get_all_groups_from_db, get_user_preferences, get_all_categories
    from handlers.accounting import accounting_manager
    from handlers.monitor import get_monthly_stats
    from datetime import timezone, timedelta, datetime
    from collections import defaultdict

    beijing_tz = timezone(timedelta(hours=8))
    yesterday = (datetime.now(beijing_tz) - timedelta(days=1)).strftime('%Y-%m-%d')
    today = datetime.now(beijing_tz).strftime('%Y-%m-%d')

    # 找出所有开启了早报的用户（管理员和操作员）
    all_groups = get_all_groups_from_db()
    # 收集用户群组关系：user_id -> [group_id]
    user_groups = defaultdict(list)
    for g in all_groups:
        try:
            with sqlite3.connect(DB_PATH) as conn:
                c = conn.cursor()
                c.execute("SELECT user_id FROM group_users WHERE group_id = ?", (g['id'],))
                users = [row[0] for row in c.fetchall()]
                for uid in users:
                    user_groups[uid].append(g['id'])
        except:
            pass

    # 遍历所有开启早报的用户
    users_to_send = []
    # 获取所有打开早报的用户（从 user_preferences 表）
    try:
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT user_id FROM user_preferences WHERE daily_report_enabled = 1")
            enabled_users = [row[0] for row in c.fetchall()]
    except:
        return

    for uid in enabled_users:
        if not is_authorized(uid, require_full_access=True):
            continue  # 只有管理员/操作员才能收
        prefs = get_user_preferences(uid)
        # 按用户所在群组或全部（管理员）
        if uid == OWNER_ID:
            # 超级管理员：所有群组
            groups_to_report = all_groups
        else:
            # 正式操作员：他所在的群组
            his_groups = user_groups.get(uid, [])
            groups_to_report = [g for g in all_groups if g['id'] in his_groups]
        if not groups_to_report:
            continue

        # ---------- 构建早报内容 ----------
        report = f"📋 **每日早报** ({yesterday})\n\n"
        total_income_cny = 0.0
        total_income_usdt = 0.0
        total_expense_usdt = 0.0
        group_details = []

        for g in groups_to_report:
            stats = accounting_manager.get_stats_by_date(g['id'], yesterday)
            income_cny = stats['income_total']
            income_usdt = stats['income_usdt']
            expense = stats['expense_usdt']
            pending = stats['pending_usdt']
            if income_cny == 0 and expense == 0:
                continue
            total_income_cny += income_cny
            total_income_usdt += income_usdt
            total_expense_usdt += expense
            group_details.append(f"• {g['title']}：入 {income_cny:.2f}元 / {income_usdt:.2f}U，出 {expense:.2f}U，待 {pending:.2f}U")
            # 只列出前10个有交易的群
            if len(group_details) == 10:
                group_details.append("... 仅显示前10个")
                break

        report += f"💰 **总入款**：{total_income_cny:.2f} 元 ≈ {total_income_usdt:.2f} USDT\n"
        report += f"📤 **总下发**：{total_expense_usdt:.2f} USDT\n"
        report += f"⏳ **总待下发**：{total_income_usdt - total_expense_usdt:.2f} USDT\n\n"
        if group_details:
            report += "📊 **群组明细**\n" + "\n".join(group_details) + "\n\n"

        # 加入昨日新加入群组
        joined_yesterday = 0
        for g in all_groups:
            jt = g.get('joined_at', 0)
            if jt:
                dt = datetime.fromtimestamp(jt, tz=beijing_tz)
                if dt.strftime('%Y-%m-%d') == yesterday:
                    joined_yesterday += 1
        report += f"📁 **昨日新加入群组**：{joined_yesterday} 个\n"

        # 监控地址昨日净收入（用户自己添加的地址）
        from db import get_monitored_addresses
        my_addrs = get_monitored_addresses(user_id=uid)
        if my_addrs:
            addr_lines = []
            for addr in my_addrs:
                stats_month = await get_monthly_stats(addr['address'])
                # 由于我们需要精确到昨日，这里简化用月度统计替代，但可改为查昨日交易
                # 这里暂时显示月度净收入
                addr_lines.append(f"  {addr['note'] or addr['address'][:8]}: 月净 {stats_month['net']:.2f}U")
            if addr_lines:
                report += "🪙 **监控地址月度净收入**\n" + "\n".join(addr_lines) + "\n"

        report += f"\n📌 由记账机器人自动生成"
        try:
            await app.bot.send_message(chat_id=uid, text=report, parse_mode="Markdown")
            print(f"✅ 早报已发送至 {uid}")
        except Exception as e:
            print(f"❌ 发送早报失败 {uid}: {e}")

async def daily_report_loop(app: Application):
    await asyncio.sleep(30)
    sent_today = False
    while True:
        now = datetime.now()
        beijing_now = now.astimezone(timezone(timedelta(hours=8)))
        if beijing_now.hour == 9 and not sent_today:
            sent_today = True
            try:
                await send_daily_reports(app)
            except Exception as e:
                print(f"❌ 每日早报发送失败: {e}")
        elif beijing_now.hour != 9:
            sent_today = False
        await asyncio.sleep(60)

async def test_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    from config import OWNER_ID
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ 只有控制人可以使用")
        return
    await update.message.reply_text("⏳ 正在发送测试早报...")
    await send_daily_reports(context.application)
    await update.message.reply_text("✅ 测试早报已发送")


# ==================== main 函数 ====================

def main():
    init_db()
    from db import fix_joined_at
    fix_joined_at()
    init_operators_from_db()

    from handlers.accounting import init_accounting, handle_group_message
    init_accounting(DB_PATH)

    app = Application.builder().token(BOT_TOKEN).build()

    async def force_clean_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        from config import OWNER_ID
        if user_id != OWNER_ID:
            await update.message.reply_text("❌ 只有控制人可以使用此命令")
            return
        msg = await update.message.reply_text("🔍 开始强制检查所有群组...")
        from db import get_all_groups_from_db
        groups = get_all_groups_from_db()
        deleted, kept, errors = 0, 0, 0
        for group in groups:
            group_id = group['id']
            group_name = group.get('title', '未知')
            try:
                await context.bot.send_chat_action(chat_id=group_id, action="typing")
                kept += 1
                await msg.edit_text(f"✅ 仍在群组: {group_name}\n已检查: {kept + deleted + errors}/{len(groups)}")
            except Exception as e:
                error_msg = str(e).lower()
                if any(kw in error_msg for kw in ["chat not found", "bot was kicked", "bot is not a member"]):
                    delete_group_from_db(group_id)
                    deleted += 1
                else:
                    errors += 1
                await asyncio.sleep(0.5)
        await msg.edit_text(f"✅ 强制清理完成！\n\n删除: {deleted} 个\n保留: {kept} 个\n错误: {errors} 个")

    # 注册处理器
    app.add_handler(CommandHandler("cancel", cancel_command))
    from handlers.group_manager import skip_command
    app.add_handler(CommandHandler("skip", skip_command))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("update_ops", cmd_update_operator_info))
    app.add_handler(CommandHandler("clean", force_clean_groups))
    app.add_handler(CommandHandler("test_report", test_report))

    for handler in get_git_handlers():
        app.add_handler(handler)

    # Transfer ConversationHandler
    transfer_conv_handler = ConversationHandler(
        entry_points=[],
        states={},
        fallbacks=[CommandHandler("cancel", transfer.cancel_transfer)],
        per_message=False,
    )
    app.add_handler(transfer_conv_handler, group=1)

    # Broadcast
    for handler in broadcast.get_handlers():
        app.add_handler(handler, group=1)

    # Monitor
    monitor_conv_handler = monitor.get_monitor_conversation_handler()
    app.add_handler(monitor_conv_handler)
    app.add_handler(CommandHandler("cancel_monitor", monitor.monitor_cancel))

    # 内联按钮路由
    app.add_handler(CallbackQueryHandler(button_router), group=0)

    # ========== 个人中心 ConversationHandler ==========
    profile_conv = ConversationHandler(
        entry_points=[
            # 子按钮回调
            CallbackQueryHandler(profile_stats, pattern="^profile_stats$"),
            CallbackQueryHandler(profile_addresses, pattern="^profile_addresses$"),
            CallbackQueryHandler(profile_toggle_notify, pattern="^profile_toggle_notify$"),
            CallbackQueryHandler(profile_signature_start, pattern="^profile_signature$"),
            CallbackQueryHandler(profile_contact, pattern="^profile_contact$"),
            CallbackQueryHandler(profile_feedback_start, pattern="^profile_feedback$"),
            CallbackQueryHandler(profile_export_data, pattern="^profile_export$"),
            CallbackQueryHandler(profile_report_toggle, pattern="^profile_report_toggle$"),
            CallbackQueryHandler(profile_back, pattern="^profile_back$"),
        ],
        states={
            SET_SIGNATURE: [
                MessageHandler(filters.TEXT, profile_signature_input)
            ],
            FEEDBACK: [
                MessageHandler(filters.TEXT, profile_feedback_input)
            ],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        per_message=False,
        allow_reentry=True,
    )
    app.add_handler(profile_conv, group=1)

    # 三层私聊处理器
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
        keyboard_handler
    ), group=0)

    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
        module_input_handler
    ), group=1)

    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
        ai_chat_handler
    ), group=2)

    # 群组消息
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
        handle_group_message
    ), group=1)

    # 全局群组消息
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & ~filters.COMMAND, 
        auto_save_group
    ), group=2)

    app.add_handler(ChatMemberHandler(on_bot_join_or_leave, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(get_service_message_handler())

    async def post_init(app: Application):
        await auto_classify_all_groups_on_startup(app)
        asyncio.create_task(daily_report_loop(app))
        asyncio.create_task(cleanup_expired_states())
        async def monitor_check_loop():
            await asyncio.sleep(10)
            class ContextWrapper:
                def __init__(self, bot):
                    self.bot = bot
            ctx = ContextWrapper(app.bot)
            while True:
                try:
                    await monitor.check_address_transactions(ctx)
                    await asyncio.sleep(30)
                except Exception as e:
                    print(f"⚠️ 监控检查失败: {e}")
                    await asyncio.sleep(30)
        asyncio.create_task(monitor_check_loop())

    app.post_init = post_init

    print("=" * 50)
    print("🤖 机器人启动成功...")
    print("=" * 50)

    app.run_polling()

if __name__ == "__main__":
    main()
