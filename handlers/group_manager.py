# handlers/group_manager.py - 完整功能版

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

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理群组消息中的记账指令"""
    chat = update.effective_chat
    message = update.message

    if not message or chat.type not in ['group', 'supergroup']:
        return

    text = message.text.strip() if message.text else ""

    if not text:
        return

    # 这里可以添加其他处理逻辑
    pass

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

    # 设置用户状态，等待输入分类名称
    user_states[user_id] = {"action": "add_category_name"}

    await query.message.edit_text(
        "➕ **创建新分类**\n\n"
        "请输入分类名称（如：VIP群组）：\n\n"
        "❌ 输入 /cancel 取消",
        parse_mode="Markdown"
    )

async def add_category_name(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """接收分类名称"""
    name = update.message.text.strip()
    print(f"[DEBUG] add_category_name: {name}")

    if name == "/cancel":
        del user_states[user_id]
        await update.message.reply_text("❌ 已取消")
        return

    if len(name) < 2:
        await update.message.reply_text("❌ 分类名称至少2个字符，请重新输入：")
        return

    categories = get_all_categories()
    if any(cat['name'] == name for cat in categories):
        await update.message.reply_text(f"❌ 分类「{name}」已存在，请使用其他名称：")
        return

    # 保存临时数据
    user_states[user_id] = {"action": "add_category_desc", "name": name}
    await update.message.reply_text(
        f"📝 分类名称：{name}\n\n"
        "请输入分类描述（可选，直接发送 /skip 跳过）："
    )

async def add_category_desc(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """接收分类描述"""
    text = update.message.text.strip()
    print(f"[DEBUG] add_category_desc: {text}")

    if text == "/skip":
        description = ""
    elif text == "/cancel":
        del user_states[user_id]
        await update.message.reply_text("❌ 已取消")
        return
    else:
        description = text

    name = user_states[user_id].get("name", "")

    if add_category(name, description):
        await update.message.reply_text(f"✅ 分类「{name}」创建成功！")
    else:
        await update.message.reply_text(f"❌ 创建失败")

    # 清除状态
    del user_states[user_id]

    # 返回主菜单
    await update.message.reply_text(
        "请点击下方按钮返回：",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ 返回群组管理", callback_data="group_manager")
        ]])
    )

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

    print(f"[DEBUG] handle_text_input 收到: {message.text}, user_id: {user_id}")

    if user_id not in user_states:
        return

    state = user_states[user_id]
    action = state.get("action")

    if action == "add_category_name":
        await add_category_name(update, context, user_id)
    elif action == "add_category_desc":
        await add_category_desc(update, context, user_id)

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
    'show_group_list_page',
    'handle_group_pagination',
    'filter_groups',
    'user_states',
    'ITEMS_PER_PAGE'
]
