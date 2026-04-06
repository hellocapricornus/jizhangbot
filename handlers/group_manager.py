# handlers/group_manager.py - 完整功能版
import time
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from auth import is_authorized
from db import (
    get_all_groups_from_db, get_all_categories, update_group_category, 
    add_category, delete_category, get_groups_by_category
)

# 存储用户输入状态的字典
user_states = {}

# 分页常量
ITEMS_PER_PAGE = 10

# 用户状态超时清理（1分钟）
USER_STATE_TIMEOUT = 60

async def cleanup_expired_states():
    """清理过期的用户状态"""
    current_time = time.time()
    expired_users = []

    for user_id, state in user_states.items():
        if 'timestamp' not in state:
            state['timestamp'] = current_time
        elif current_time - state['timestamp'] > USER_STATE_TIMEOUT:
            expired_users.append(user_id)

    for user_id in expired_users:
        del user_states[user_id]
        print(f"[清理] 已清除用户 {user_id} 的过期状态")

async def group_manager_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """群组管理主菜单"""
    query = update.callback_query
    user_id = query.from_user.id

    print(f"[DEBUG] group_manager_menu 被调用")

    if not is_authorized(user_id):
        await query.answer("❌ 无权限", show_alert=True)
        return

    await query.answer()

    # 清除用户状态
    if user_id in user_states:
        del user_states[user_id]

    # 获取统计信息
    categories = get_all_categories()
    groups_by_cat = get_groups_by_category()
    total_groups = sum(groups_by_cat.values())

    keyboard = [
        [InlineKeyboardButton("📊 查看统计", callback_data="gm_stats")],
        [InlineKeyboardButton("📁 查看所有分类", callback_data="gm_list_cats")],
        [InlineKeyboardButton("➕ 创建分类", callback_data="gm_add_cat")],
        [InlineKeyboardButton("🏷️ 设置群组分类", callback_data="gm_set_cat")],
        [InlineKeyboardButton("🗑️ 删除分类", callback_data="gm_del_cat")],
        [InlineKeyboardButton("◀️ 返回主菜单", callback_data="main_menu")]
    ]

    text = f"📁 **群组分类管理**\n\n"
    text += f"📊 总群组数：**{total_groups}** 个\n"
    text += f"🏷️ 分类数量：**{len(categories)}** 个\n\n"
    text += "💡 点击下方按钮进行操作"

    try:
        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        print(f"[DEBUG] 菜单显示成功")
    except Exception as e:
        print(f"[DEBUG] 菜单显示失败: {e}")
        await query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示群组统计"""
    query = update.callback_query
    await query.answer()
    print(f"[DEBUG] show_stats 被调用")

    groups_by_cat = get_groups_by_category()
    categories = get_all_categories()

    text = "📊 **群组统计**\n\n"
    for cat in categories:
        cat_name = cat['name']
        count = groups_by_cat.get(cat_name, 0)
        text += f"• **{cat_name}**：{count} 个群组\n"
    text += f"\n总计：**{sum(groups_by_cat.values())}** 个群组"

    keyboard = [[InlineKeyboardButton("◀️ 返回", callback_data="group_manager")]]

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def list_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看所有分类"""
    query = update.callback_query
    await query.answer()
    print(f"[DEBUG] list_categories 被调用")

    categories = get_all_categories()
    groups_by_cat = get_groups_by_category()

    text = "📁 **现有分类**\n\n"
    for cat in categories:
        cat_name = cat['name']
        count = groups_by_cat.get(cat_name, 0)
        text += f"• **{cat_name}** ({count}个群组)\n"

    keyboard = [[InlineKeyboardButton("◀️ 返回", callback_data="group_manager")]]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ==================== 创建分类 ====================
async def add_category_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始添加分类"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    print(f"[DEBUG] add_category_start 被调用")

    # ✅ 添加时间戳
    user_states[user_id] = {
        "action": "add_category_name",
        "timestamp": time.time()
    }

    await query.message.edit_text(
        "➕ **创建新分类**\n\n"
        "请输入分类名称（如：VIP群组）：\n\n"
        "❌ 输入 /cancel 取消",
        parse_mode="Markdown"
    )

async def add_category_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收分类名称"""
    user_id = update.effective_user.id
    message = update.message
    text = message.text.strip()

    # 🔥 处理 /cancel（双重保险）
    if text == "/cancel":
        if user_id in user_states:
            del user_states[user_id]
        await message.reply_text("❌ 已取消创建分类")
        from handlers.menu import get_main_menu
        await message.reply_text("请选择功能：", reply_markup=get_main_menu())
        return

    # 验证分类名称
    if len(text) < 2:
        await message.reply_text("❌ 分类名称至少2个字符，请重新输入：\n\n输入 /cancel 取消")
        return

    categories = get_all_categories()
    if any(cat['name'] == text for cat in categories):
        await message.reply_text(f"❌ 分类「{text}」已存在，请使用其他名称：\n\n输入 /cancel 取消")
        return

    # 保存临时数据
    user_states[user_id] = {"action": "add_category_desc", "name": text}
    await message.reply_text(
        f"📝 分类名称：{text}\n\n"
        "请输入分类描述（可选，直接发送 /skip 跳过）：\n\n"
        "❌ 输入 /cancel 取消"
    )


async def add_category_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收分类描述"""
    user_id = update.effective_user.id
    message = update.message
    text = message.text.strip()

    # 🔥 处理 /cancel
    if text == "/cancel":
        if user_id in user_states:
            del user_states[user_id]
        await message.reply_text("❌ 已取消创建分类")
        from handlers.menu import get_main_menu
        await message.reply_text("请选择功能：", reply_markup=get_main_menu())
        return

    # 🔥 处理 /skip
    if text == "/skip":
        description = ""
    else:
        description = text

    # 获取分类名称
    state = user_states.get(user_id, {})
    name = state.get("name", "")

    if not name:
        await message.reply_text("❌ 会话已过期，请重新开始")
        if user_id in user_states:
            del user_states[user_id]
        return

    # 创建分类
    if add_category(name, description):
        await message.reply_text(f"✅ 分类「{name}」创建成功！")
    else:
        await message.reply_text(f"❌ 创建失败")

    # 清除状态
    if user_id in user_states:
        del user_states[user_id]

    # 返回主菜单
    from handlers.menu import get_main_menu
    await message.reply_text("请选择功能：", reply_markup=get_main_menu())

# ==================== 删除分类 ====================
async def delete_category_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始删除分类"""
    query = update.callback_query
    await query.answer()
    print(f"[DEBUG] delete_category_start 被调用")

    categories = get_all_categories()
    deletable = [cat for cat in categories if cat['name'] != '未分类']

    if not deletable:
        await query.message.edit_text("⚠️ 没有可删除的分类（「未分类」不能删除）")
        return

    keyboard = []
    for cat in deletable:
        keyboard.append([InlineKeyboardButton(f"🗑️ {cat['name']}", callback_data=f"del_cat_{cat['name']}")])
    keyboard.append([InlineKeyboardButton("◀️ 返回", callback_data="group_manager")])

    await query.message.edit_text(
        "🗑️ **删除分类**\n\n"
        "选择要删除的分类：",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def delete_category_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """确认删除分类"""
    query = update.callback_query
    category_name = query.data.replace("del_cat_", "")
    await query.answer()
    print(f"[DEBUG] delete_category_confirm: {category_name}")

    if delete_category(category_name):
        await query.message.edit_text(f"✅ 已删除分类「{category_name}」")
    else:
        await query.message.edit_text(f"❌ 删除失败")

    await asyncio.sleep(1)
    # 返回主菜单
    await group_manager_menu(update, context)

# ==================== 设置群组分类 ====================
async def set_group_category_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始设置群组分类"""
    query = update.callback_query
    await query.answer()
    print(f"[DEBUG] set_group_category_start 被调用")

    # 获取所有群组
    groups = get_all_groups_from_db()

    if not groups:
        await query.message.edit_text("📭 暂无群组")
        return

    # 初始化分页数据
    context.user_data['group_list'] = groups
    context.user_data['current_page'] = 0
    context.user_data['selecting_group'] = True

    # 显示第一页
    await show_group_list_page(update, context)

async def show_group_list_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示群组列表页面"""
    groups = context.user_data.get('group_list', [])
    current_page = context.user_data.get('current_page', 0)

    if not groups:
        if isinstance(update, Update) and update.callback_query:
            await update.callback_query.message.edit_text("📭 暂无群组")
        else:
            await update.message.reply_text("📭 暂无群组")
        return

    # 计算分页
    total_pages = (len(groups) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start_idx = current_page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(groups))
    current_groups = groups[start_idx:end_idx]

    # 构建按钮列表
    keyboard = []

    # 添加筛选按钮
    keyboard.append([
        InlineKeyboardButton("📋 未分类", callback_data="filter_uncategorized"),
        InlineKeyboardButton("✅ 已分类", callback_data="filter_categorized")
    ])

    # 显示群组列表
    for group in current_groups:
        title = group['title'][:25]
        current_cat = group.get('category', '未分类')
        keyboard.append([InlineKeyboardButton(
            f"{title} (当前: {current_cat})", 
            callback_data=f"sel_group_{group['id']}"
        )])

    # 添加分页按钮
    nav_buttons = []
    if current_page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data="group_page_prev"))
    if current_page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data="group_page_next"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    # 添加刷新和返回按钮
    keyboard.append([
        InlineKeyboardButton("🔄 刷新", callback_data="refresh_group_list"),
        InlineKeyboardButton("◀️ 返回", callback_data="group_manager")
    ])

    # 显示消息
    text = f"🏷️ **设置群组分类**\n\n"
    text += f"请选择要设置分类的群组：\n"
    text += f"共 **{len(groups)}** 个群组，第 **{current_page + 1}/{total_pages}** 页\n\n"
    text += f"📌 **筛选选项**：\n"
    text += f"• 未分类：显示未设置分类的群组\n"
    text += f"• 已分类：显示已设置分类的群组"

    if isinstance(update, Update) and update.callback_query:
        await update.callback_query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

async def handle_group_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理群组列表的分页"""
    query = update.callback_query
    data = query.data

    if data == "group_page_prev":
        current_page = context.user_data.get('current_page', 0)
        context.user_data['current_page'] = max(0, current_page - 1)
        await show_group_list_page(update, context)

    elif data == "group_page_next":
        current_page = context.user_data.get('current_page', 0)
        groups = context.user_data.get('group_list', [])
        total_pages = (len(groups) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        context.user_data['current_page'] = min(total_pages - 1, current_page + 1)
        await show_group_list_page(update, context)

    elif data == "refresh_group_list":
        # 刷新列表，恢复显示所有群组
        groups = get_all_groups_from_db()
        context.user_data['group_list'] = groups
        context.user_data['current_page'] = 0
        context.user_data.pop('filter_type', None)
        await show_group_list_page(update, context)

    elif data == "filter_uncategorized":
        await filter_groups(update, context, "uncategorized")

    elif data == "filter_categorized":
        await filter_groups(update, context, "categorized")

async def filter_groups(update: Update, context: ContextTypes.DEFAULT_TYPE, filter_type: str):
    """筛选群组"""
    query = update.callback_query
    await query.answer()

    all_groups = get_all_groups_from_db()

    if filter_type == "uncategorized":
        # 筛选未分类的群组
        filtered_groups = [g for g in all_groups if g.get('category', '未分类') == '未分类']
        filter_name = "未分类"
    else:  # categorized
        # 筛选已分类的群组
        filtered_groups = [g for g in all_groups if g.get('category', '未分类') != '未分类']
        filter_name = "已分类"

    if not filtered_groups:
        await query.message.edit_text(f"📭 暂无{filter_name}的群组")
        await asyncio.sleep(1)
        await show_group_list_page(update, context)
        return

    # 更新上下文中的群组列表
    context.user_data['group_list'] = filtered_groups
    context.user_data['current_page'] = 0
    context.user_data['filter_type'] = filter_type

    # 显示筛选后的群组列表
    await show_group_list_page(update, context)

async def select_group_for_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """选择要设置分类的群组"""
    query = update.callback_query
    group_id = query.data.replace("sel_group_", "")
    await query.answer()
    print(f"[DEBUG] select_group_for_category: {group_id}")

    # 保存选中的群组ID
    context.user_data['selected_group_id'] = group_id

    # 显示分类列表
    categories = get_all_categories()
    keyboard = []

    # 添加"未分类"选项
    keyboard.append([InlineKeyboardButton(f"📂 未分类", callback_data=f"set_cat_未分类_{group_id}")])

    # 添加其他分类
    for cat in categories:
        if cat['name'] != '未分类':  # 避免重复添加未分类
            keyboard.append([InlineKeyboardButton(f"📁 {cat['name']}", callback_data=f"set_cat_{cat['name']}_{group_id}")])

    # 添加返回按钮
    keyboard.append([InlineKeyboardButton("◀️ 返回", callback_data="gm_set_cat")])

    await query.message.edit_text(
        "🏷️ **选择分类**\n\n"
        "请选择要分配给该群组的分类：\n"
        "• 未分类：群组尚未分类\n"
        "• 其他：已建立的分类",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def set_group_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置群组的分类"""
    query = update.callback_query
    data_parts = query.data.replace("set_cat_", "").split("_")
    category_name = data_parts[0]
    group_id = data_parts[1]
    await query.answer()
    print(f"[DEBUG] set_group_category: {category_name} for {group_id}")

    if update_group_category(group_id, category_name):
        # 获取群组信息
        groups = get_all_groups_from_db()
        group_info = next((g for g in groups if g['id'] == group_id), None)
        group_title = group_info['title'] if group_info else group_id

        await query.message.edit_text(
            f"✅ 已将群组「{group_title}」的分类设置为「{category_name}」"
        )

        # 刷新群组列表
        await asyncio.sleep(1)

        # 刷新列表，显示所有群组
        all_groups = get_all_groups_from_db()
        context.user_data['group_list'] = all_groups
        context.user_data['current_page'] = 0
        context.user_data.pop('filter_type', None)

        await show_group_list_page(update, context)
    else:
        await query.message.edit_text(f"❌ 设置失败")
        await asyncio.sleep(1)
        await group_manager_menu(update, context)

# ==================== 文本输入处理 ====================
async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理文本输入（用于创建分类）"""
    user_id = update.effective_user.id
    message = update.message
    text = message.text.strip()

    print(f"[DEBUG] handle_text_input 收到: {message.text}, user_id: {user_id}")

    if user_id not in user_states:
        return

    # 🔥 全局处理 /cancel
    if text == "/cancel":
        if user_id in user_states:
            del user_states[user_id]
        await message.reply_text("❌ 已取消操作")
        from handlers.menu import get_main_menu
        await message.reply_text("请选择功能：", reply_markup=get_main_menu())
        return

    state = user_states[user_id]
    action = state.get("action")

    # 🔥 处理 /skip 只在特定状态有效
    if text == "/skip":
        if action == "add_category_desc":
            # 跳过描述
            await add_category_desc(update, context)
            return
        else:
            await message.reply_text("❌ 当前状态不支持 /skip")
            return

    # 处理其他输入
    if action == "add_category_name":
        await add_category_name(update, context)
    elif action == "add_category_desc":
        await add_category_desc(update, context)

async def add_category_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收分类名称"""
    user_id = update.effective_user.id
    message = update.message
    text = message.text.strip()

    # 🔥 处理 /cancel（双重保险）
    if text == "/cancel":
        if user_id in user_states:
            del user_states[user_id]
        await message.reply_text("❌ 已取消创建分类")
        from handlers.menu import get_main_menu
        await message.reply_text("请选择功能：", reply_markup=get_main_menu())
        return

    # 验证分类名称
    if len(text) < 2:
        await message.reply_text("❌ 分类名称至少2个字符，请重新输入：\n\n输入 /cancel 取消")
        return

    categories = get_all_categories()
    if any(cat['name'] == text for cat in categories):
        await message.reply_text(f"❌ 分类「{text}」已存在，请使用其他名称：\n\n输入 /cancel 取消")
        return

    # 保存临时数据
    user_states[user_id] = {"action": "add_category_desc", "name": text}
    await message.reply_text(
        f"📝 分类名称：{text}\n\n"
        "请输入分类描述（可选，直接发送 /skip 跳过）：\n\n"
        "❌ 输入 /cancel 取消"
    )

async def add_category_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收分类描述"""
    user_id = update.effective_user.id
    message = update.message
    text = message.text.strip()

    # 🔥 处理 /cancel
    if text == "/cancel":
        if user_id in user_states:
            del user_states[user_id]
        await message.reply_text("❌ 已取消创建分类")
        from handlers.menu import get_main_menu
        await message.reply_text("请选择功能：", reply_markup=get_main_menu())
        return

    # 🔥 处理 /skip
    if text == "/skip":
        description = ""
    else:
        description = text

    # 获取分类名称
    state = user_states.get(user_id, {})
    name = state.get("name", "")

    if not name:
        await message.reply_text("❌ 会话已过期，请重新开始")
        if user_id in user_states:
            del user_states[user_id]
        return

    # 创建分类
    if add_category(name, description):
        await message.reply_text(f"✅ 分类「{name}」创建成功！")
    else:
        await message.reply_text(f"❌ 创建失败")

    # 清除状态
    if user_id in user_states:
        del user_states[user_id]

    # 返回主菜单
    from handlers.menu import get_main_menu
    await message.reply_text("请选择功能：", reply_markup=get_main_menu())

# group_manager.py - 确保 cancel 命令清除状态后返回主菜单

async def handle_cancel_in_group_manager(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """群组管理专用的取消处理"""
    user_id = update.effective_user.id
    print(f"[DEBUG] handle_cancel_in_group_manager 被调用, user_id: {user_id}")

    # 清除状态
    if user_id in user_states:
        print(f"[DEBUG] 清除 user_states[{user_id}], 当前状态: {user_states[user_id]}")
        del user_states[user_id]

    # ✅ 同时清除 active_module
    context.user_data.pop("active_module", None)

    # 发送取消消息
    if update.message:
        await update.message.reply_text("❌ 已取消创建分类")
    elif update.callback_query:
        await update.callback_query.message.reply_text("❌ 已取消创建分类")

    # 返回主菜单
    from handlers.menu import get_main_menu

    if update.message:
        await update.message.reply_text(
            "请选择功能：",
            reply_markup=get_main_menu()
        )
    elif update.callback_query:
        await update.callback_query.message.reply_text(
            "请选择功能：",
            reply_markup=get_main_menu()
        )

# group_manager.py - 添加 skip 命令处理

async def skip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /skip 命令"""
    user_id = update.effective_user.id

    print(f"[DEBUG] skip_command 被调用, user_id: {user_id}")

    # 检查是否在群组管理状态
    if user_id not in user_states:
        await update.message.reply_text("❌ 当前没有进行中的操作")
        return

    state = user_states[user_id]
    action = state.get("action")

    # 只有在 add_category_desc 状态才能跳过
    if action == "add_category_desc":
        # 直接调用 add_category_desc 处理跳过
        await add_category_desc(update, context)
    else:
        await update.message.reply_text("❌ 当前状态不支持 /skip")

# 导出所有函数
__all__ = [
    'group_manager_menu',
    'show_stats',
    'list_categories',
    'add_category_start',
    'delete_category_start',
    'delete_category_confirm',
    'set_group_category_start',
    'select_group_for_category',
    'set_group_category',
    'handle_text_input',
    'handle_cancel_in_group_manager',  # 新增
    'skip_command',  # 🔥 新增
    'show_group_list_page',
    'handle_group_pagination',
    'filter_groups',
    'user_states',
    'ITEMS_PER_PAGE'
]
