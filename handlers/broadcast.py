#broadcast.py
import logging
import random
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackQueryHandler, MessageHandler, ConversationHandler, 
    ContextTypes, filters, CommandHandler
)
from telegram.error import RetryAfter, TimedOut, NetworkError
from auth import is_authorized
from db import get_all_groups_from_db, delete_group_from_db, get_all_categories

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 状态定义 ---
(
    BC_SELECT_GROUPS,
    BC_INPUT_MESSAGE,
    BC_CONFIRM_SEND
) = range(3)

# 分页常量
GROUPS_PER_PAGE = 8

# 在文件开头添加国家代码映射（可以根据需要扩展）
COUNTRY_EMOJI = {
    '中国': '🇨🇳', '美国': '🇺🇸', '日本': '🇯🇵', '韩国': '🇰🇷',
    '英国': '🇬🇧', '法国': '🇫🇷', '德国': '🇩🇪', '意大利': '🇮🇹',
    '西班牙': '🇪🇸', '葡萄牙': '🇵🇹', '荷兰': '🇳🇱', '瑞士': '🇨🇭',
    '瑞典': '🇸🇪', '挪威': '🇳🇴', '丹麦': '🇩🇰', '芬兰': '🇫🇮',
    '俄罗斯': '🇷🇺', '澳大利亚': '🇦🇺', '新西兰': '🇳🇿', '加拿大': '🇨🇦',
    '巴西': '🇧🇷', '阿根廷': '🇦🇷', '墨西哥': '🇲🇽', '印度': '🇮🇳',
    '泰国': '🇹🇭', '越南': '🇻🇳', '新加坡': '🇸🇬', '马来西亚': '🇲🇾',
    '印度尼西亚': '🇮🇩', '菲律宾': '🇵🇭', '土耳其': '🇹🇷', '阿联酋': '🇦🇪',
    '沙特': '🇸🇦', '南非': '🇿🇦', '埃及': '🇪🇬', '希腊': '🇬🇷',
    '爱尔兰': '🇮🇪', '波兰': '🇵🇱', '捷克': '🇨🇿', '奥地利': '🇦🇹',
    '比利时': '🇧🇪', '匈牙利': '🇭🇺',
    '尼日利亚': '🇳🇬', '乌克兰': '🇺🇦', '罗马尼亚': '🇷🇴', '保加利亚': '🇧🇬',
    '塞尔维亚': '🇷🇸', '克罗地亚': '🇭🇷', '斯洛文尼亚': '🇸🇮', '爱沙尼亚': '🇪🇪',
    '拉脱维亚': '🇱🇻', '立陶宛': '🇱🇹', '白俄罗斯': '🇧🇾', '摩尔多瓦': '🇲🇩',
    '格鲁吉亚': '🇬🇪', '亚美尼亚': '🇦🇲', '阿塞拜疆': '🇦🇿', '哈萨克斯坦': '🇰🇿',
    '乌兹别克斯坦': '🇺🇿', '土库曼斯坦': '🇹🇲', '吉尔吉斯斯坦': '🇰🇬', '塔吉克斯坦': '🇹🇯',
    '蒙古': '🇲🇳', '朝鲜': '🇰🇵', '柬埔寨': '🇰🇭', '老挝': '🇱🇦',
    '缅甸': '🇲🇲', '斯里兰卡': '🇱🇰', '巴基斯坦': '🇵🇰', '孟加拉国': '🇧🇩',
    '尼泊尔': '🇳🇵', '不丹': '🇧🇹', '马尔代夫': '🇲🇻', '伊朗': '🇮🇷',
    '伊拉克': '🇮🇶', '科威特': '🇰🇼', '卡塔尔': '🇶🇦', '巴林': '🇧🇭',
    '阿曼': '🇴🇲', '也门': '🇾🇪', '约旦': '🇯🇴', '黎巴嫩': '🇱🇧',
    '叙利亚': '🇸🇾', '以色列': '🇮🇱', '巴勒斯坦': '🇵🇸', '塞浦路斯': '🇨🇾',
    '阿尔及利亚': '🇩🇿', '摩洛哥': '🇲🇦', '突尼斯': '🇹🇳', '利比亚': '🇱🇾',
    '苏丹': '🇸🇩', '埃塞俄比亚': '🇪🇹', '肯尼亚': '🇰🇪', '坦桑尼亚': '🇹🇿',
    '乌干达': '🇺🇬', '卢旺达': '🇷🇼', '刚果': '🇨🇩', '安哥拉': '🇦🇴',
    '纳米比亚': '🇳🇦', '博茨瓦纳': '🇧🇼', '赞比亚': '🇿🇲', '津巴布韦': '🇿🇼',
    '莫桑比克': '🇲🇿', '马达加斯加': '🇲🇬', '毛里求斯': '🇲🇺', '塞舌尔': '🇸🇨',
    '加纳': '🇬🇭', '科特迪瓦': '🇨🇮', '喀麦隆': '🇨🇲', '塞内加尔': '🇸🇳',
    '马里': '🇲🇱', '布基纳法索': '🇧🇫', '尼日尔': '🇳🇪', '乍得': '🇹🇩',
    '中非': '🇨🇫', '加蓬': '🇬🇦', '赤道几内亚': '🇬🇶', '吉布提': '🇩🇯',
    '索马里': '🇸🇴', '厄立特里亚': '🇪🇷', '毛里塔尼亚': '🇲🇷', '冈比亚': '🇬🇲',
    '几内亚': '🇬🇳', '几内亚比绍': '🇬🇼', '塞拉利昂': '🇸🇱', '利比里亚': '🇱🇷',
    '冰岛': '🇮🇸', '马耳他': '🇲🇹', '卢森堡': '🇱🇺', '摩纳哥': '🇲🇨',
    '列支敦士登': '🇱🇮', '安道尔': '🇦🇩', '圣马力诺': '🇸🇲', '梵蒂冈': '🇻🇦',
    '古巴': '🇨🇺', '牙买加': '🇯🇲', '海地': '🇭🇹', '多米尼加': '🇩🇴',
    '波多黎各': '🇵🇷', '巴哈马': '🇧🇸', '特立尼达和多巴哥': '🇹🇹', '巴巴多斯': '🇧🇧',
    '圣卢西亚': '🇱🇨', '格林纳达': '🇬🇩', '安提瓜和巴布达': '🇦🇬', '圣基茨和尼维斯': '🇰🇳',
    '哥伦比亚': '🇨🇴', '委内瑞拉': '🇻🇪', '厄瓜多尔': '🇪🇨', '秘鲁': '🇵🇪',
    '玻利维亚': '🇧🇴', '巴拉圭': '🇵🇾', '乌拉圭': '🇺🇾', '圭亚那': '🇬🇾',
    '苏里南': '🇸🇷', '斐济': '🇫🇯', '巴布亚新几内亚': '🇵🇬', '所罗门群岛': '🇸🇧',
    '瓦努阿图': '🇻🇺', '萨摩亚': '🇼🇸', '汤加': '🇹🇴', '密克罗尼西亚': '🇫🇲',
    '马绍尔群岛': '🇲🇭', '帕劳': '🇵🇼', '瑙鲁': '🇳🇷', '图瓦卢': '🇹🇻', '基里巴斯': '🇰🇮',
}


def get_category_icon(category_name: str) -> str:
    """根据分类名称返回对应的图标"""
    # 精确匹配国家名称
    if category_name in COUNTRY_EMOJI:
        return COUNTRY_EMOJI[category_name]

    # 尝试匹配部分关键词（如"德国代理" -> "🇩🇪"）
    for country, emoji in COUNTRY_EMOJI.items():
        if country in category_name:
            return emoji

    # 默认使用📁
    return "📁"
    
# --- 核心逻辑：同步与清理 ---
async def sync_and_clean_groups(context: ContextTypes.DEFAULT_TYPE):
    """同步并清理无效群组"""
    db_groups = get_all_groups_from_db()  # 使用正确的函数名

    valid_groups = []
    logger.info(f"开始同步群组，数据库记录数：{len(db_groups)}")

    for g in db_groups:
        gid = g['id']
        try:
            chat = await context.bot.get_chat(gid)
            if chat.title != g['title']:
                g['title'] = chat.title
                # 如果群名变更，保存
                from db import save_group
                save_group(gid, chat.title, g.get('category', '未分类'))  # 保留原有分类
            valid_groups.append(g)
        except Exception as e:
            logger.warning(f"检测到已退出群组，正在删除：{gid} ({g['title']}) - {e}")
            from db import delete_group_from_db
            delete_group_from_db(gid)

    logger.info(f"同步完成。有效群组：{len(valid_groups)}")
    return valid_groups

# --- 状态 1: 选择群组 ---

async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """入口：权限校验 -> 同步群组 -> 显示列表"""
    query = update.callback_query
    user_id = query.from_user.id

    # 完整权限检查（禁止临时操作人）
    if not is_authorized(user_id, require_full_access=True):
        await query.answer("❌ 无权限", show_alert=True)
        await query.message.reply_text("❌ 管理人/操作员才能使用，如需使用请联系 @ChinaEdward")
        return

    # 🔥 设置广播状态标记
    context.user_data["in_broadcast"] = True

    # 🔥 重要：开始新对话前，清理所有旧数据
    keys = ["bc_all_groups", "bc_selected_ids", "bc_message_content", "bc_temp_target_ids",
                "bc_selected_category", "bc_batches", "bc_current_batch", "bc_batch_results",
                "bc_waiting_for_next", "bc_current_state", "bc_current_page"]
    for k in keys:
        if k in context.user_data:
            context.user_data.pop(k, None)

    from db import get_all_groups_from_db
    groups = get_all_groups_from_db()

    if not groups:
        # 🔥 清除广播状态
        context.user_data.pop("in_broadcast", None)
        await query.message.reply_text("⚠️ **未找到任何有效群组**\n\n请确保机器人已添加到群组中。")
        return ConversationHandler.END

    context.user_data["bc_all_groups"] = groups
    context.user_data["bc_selected_ids"] = []
    context.user_data.pop("bc_selected_category", None)  # 清除分类筛选

    await show_group_selection(update, context)
    return BC_SELECT_GROUPS

async def show_group_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """渲染群组选择界面（支持分类筛选）"""
    groups = context.user_data.get("bc_all_groups", [])
    selected_ids = context.user_data.get("bc_selected_ids", [])
    selected_category = context.user_data.get("bc_selected_category", None)
    current_page = context.user_data.get("bc_current_page", 0)

    # 如果选择了分类，筛选群组
    if selected_category and selected_category != "所有群组":
        groups = [g for g in groups if g.get('category', '未分类') == selected_category]

    total_count = len(groups)
    selected_count = len([g for g in groups if g['id'] in selected_ids])

    # 分页计算
    total_pages = (total_count + GROUPS_PER_PAGE - 1) // GROUPS_PER_PAGE if total_count > 0 else 1
    start_idx = current_page * GROUPS_PER_PAGE
    end_idx = min(start_idx + GROUPS_PER_PAGE, total_count)
    display_groups = groups[start_idx:end_idx]

    # 构建消息文本
    text = f"📢 群发任务设置\n\n"
    text += f"📊 当前显示：{total_count} 个群\n"
    if selected_category and selected_category != "所有群组":
        text += f"🏷️ 分类筛选：{selected_category}\n"
    text += f"✅ 已勾选：{selected_count} 个\n"
    if total_pages > 1:
        text += f"📄 第 {current_page + 1}/{total_pages} 页\n\n"
    else:
        text += "\n"
    text += f"👇 点击群名勾选/取消："

    keyboard = []

    # ========== 分类筛选按钮 ==========
    from db import get_all_categories
    categories = get_all_categories()
    if categories:
        keyboard.append([InlineKeyboardButton("🌍 所有群组", callback_data="bc_filter_cat_all")])
        cat_row = []
        for cat in categories:
            cat_name = cat['name']
            is_active = (selected_category == cat_name)
            icon = get_category_icon(cat_name)
            button_text = f"✅ {icon} {cat_name}" if is_active else f"{icon} {cat_name}"
            cat_row.append(InlineKeyboardButton(button_text, callback_data=f"bc_filter_cat_{cat_name}"))
            if len(cat_row) == 3:
                keyboard.append(cat_row)
                cat_row = []
        if cat_row:
            keyboard.append(cat_row)

    # ========== 群组列表（当前页） ==========
    for g in display_groups:
        gid = g["id"]
        title = g["title"]
        category = g.get('category', '未分类')
        is_selected = gid in selected_ids
        icon = "✅" if is_selected else "⬜"
        safe_title = (title[:20] + "...") if len(title) > 20 else title
        keyboard.append([
            InlineKeyboardButton(f"{icon} [{category}] {safe_title}", callback_data=f"bc_toggle_{gid}")
        ])

    # ========== 分页导航按钮 ==========
    nav_buttons = []
    if current_page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data="bc_page_prev"))
    if current_page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data="bc_page_next"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    # ========== 操作按钮 ==========
    nav_row = [
        InlineKeyboardButton("✅ 全选当前", callback_data="bc_select_all"),
        InlineKeyboardButton("🚫 清空", callback_data="bc_deselect_all")
    ]

    send_row = [
        InlineKeyboardButton("🚀 全部发送", callback_data="bc_send_all"),
        InlineKeyboardButton("📤 发送选中", callback_data="bc_send_selected")
    ]

    # 取消按钮单独一行，更加醒目
    cancel_row = [
        InlineKeyboardButton("❌ 取消群发并返回主菜单", callback_data="bc_cancel_and_exit")
    ]

    keyboard.append(nav_row)
    keyboard.append(send_row)
    keyboard.append(cancel_row)  # 添加取消按钮

    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        if update.callback_query and update.callback_query.message:
            await update.callback_query.edit_message_text(
                text, parse_mode=None, reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"编辑消息失败：{e}")

async def bc_back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """返回主菜单并结束对话"""
    query = update.callback_query
    await query.answer()

    # 发送退出提示
    await query.message.reply_text("✅ 已退出群发功能")

    # 清理所有广播相关的临时数据
    keys = ["bc_all_groups", "bc_selected_ids", "bc_message_content", "bc_temp_target_ids",
            "bc_selected_category", "bc_batches", "bc_current_batch", "bc_batch_results",
            "bc_waiting_for_next", "in_broadcast", "bc_current_page"]
    for k in keys:
        context.user_data.pop(k, None)

    # 清除 active_module
    context.user_data.pop("active_module", None)

    # 返回主菜单
    from handlers.menu import get_main_menu
    # 🔥 移除 parse_mode="Markdown"
    # 发送新消息作为主菜单
    await query.message.reply_text(
        "请选择功能：",
        reply_markup=get_main_menu(user_id)
    )
    # 可选：删除原消息，避免界面混乱
    try:
        await query.message.delete()
    except Exception:
        pass
    return ConversationHandler.END

async def bc_cancel_and_exit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer("已取消群发")

    # 清理数据
    keys = ["bc_all_groups", "bc_selected_ids", "bc_message_content", "bc_temp_target_ids",
            "bc_selected_category", "bc_batches", "bc_current_batch", "bc_batch_results",
            "bc_waiting_for_next", "in_broadcast", "active_module", "bc_current_page"]
    for k in keys:
        context.user_data.pop(k, None)

    from handlers.menu import get_main_menu

    # 直接发送新消息
    await query.message.reply_text(
        "✅ 已取消群发\n\n请选择功能：",
        reply_markup=get_main_menu(user_id)
    )
    # 可选删除原消息
    try:
        await query.message.delete()
    except Exception:
        pass

    return ConversationHandler.END

async def bc_filter_by_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """按分类筛选"""
    query = update.callback_query
    await query.answer()

    category = query.data.replace("bc_filter_cat_", "")

    if category == "all":
        context.user_data.pop("bc_selected_category", None)
    else:
        context.user_data["bc_selected_category"] = category

    # 清空当前选中
    context.user_data["bc_selected_ids"] = []
    # 重置页码
    context.user_data["bc_current_page"] = 0

    await show_group_selection(update, context)
    return BC_SELECT_GROUPS

async def bc_toggle_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """切换单个群组的选择状态"""
    query = update.callback_query
    await query.answer()

    gid = query.data.replace("bc_toggle_", "")
    selected_ids = context.user_data.get("bc_selected_ids", [])

    if gid in selected_ids:
        selected_ids.remove(gid)
    else:
        selected_ids.append(gid)

    context.user_data["bc_selected_ids"] = selected_ids
    await show_group_selection(update, context)
    return BC_SELECT_GROUPS

async def bc_select_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """全选当前分类下的所有群组（所有页）"""
    query = update.callback_query
    await query.answer("已全选")

    groups = context.user_data.get("bc_all_groups", [])
    selected_category = context.user_data.get("bc_selected_category", None)

    if selected_category and selected_category != "所有群组":
        groups = [g for g in groups if g.get('category', '未分类') == selected_category]

    context.user_data["bc_selected_ids"] = [g["id"] for g in groups]
    # 重置页码（可选，保持当前页）
    await show_group_selection(update, context)
    return BC_SELECT_GROUPS

async def bc_page_prev(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """上一页"""
    query = update.callback_query
    await query.answer()
    current_page = context.user_data.get("bc_current_page", 0)
    context.user_data["bc_current_page"] = max(0, current_page - 1)
    await show_group_selection(update, context)
    return BC_SELECT_GROUPS


async def bc_page_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """下一页"""
    query = update.callback_query
    await query.answer()
    current_page = context.user_data.get("bc_current_page", 0)
    context.user_data["bc_current_page"] = current_page + 1
    await show_group_selection(update, context)
    return BC_SELECT_GROUPS

async def bc_deselect_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """清空所有选中"""
    query = update.callback_query
    await query.answer("已清空")
    context.user_data["bc_selected_ids"] = []
    await show_group_selection(update, context)
    return BC_SELECT_GROUPS

async def bc_prepare_send(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str):
    """
    准备发送
    mode: 'all' -> 忽略勾选，发所有
    mode: 'selected' -> 只发勾选的
    """
    query = update.callback_query
    await query.answer()

    all_groups = context.user_data.get("bc_all_groups", [])
    selected_category = context.user_data.get("bc_selected_category", None)

    # 如果选择了分类，只考虑该分类下的群组
    if selected_category and selected_category != "所有群组":
        all_groups = [g for g in all_groups if g.get('category', '未分类') == selected_category]

    current_selected = context.user_data.get("bc_selected_ids", [])

    target_ids = []
    mode_text = ""

    if mode == "all":
        target_ids = [g["id"] for g in all_groups]
        mode_text = "✅ 模式：全部群组 (无视勾选)"
    else:
        if not current_selected:
            await query.message.reply_text("⚠️ 您未勾选任何群组！\n请先勾选或直接点击'全部发送'。")
            return None  # 改为返回 None，明确表示不改变状态
        target_ids = current_selected
        mode_text = "✅ 模式：仅选中群组"

    # 临时存储目标 ID
    context.user_data["bc_temp_target_ids"] = target_ids

    # broadcast.py - 修改 bc_prepare_send 函数中的这段代码

    try:
        # 添加取消按钮的键盘
        cancel_keyboard = [[InlineKeyboardButton("❌ 取消群发", callback_data="bc_cancel_and_exit")]]
        cancel_markup = InlineKeyboardMarkup(cancel_keyboard)

        await query.message.reply_text(
            f"📝 确认发送配置\n\n"
            f"{mode_text}\n"
            f"🎯 目标数量：{len(target_ids)} 个\n\n"
            f"👉 请发送要群发的内容：\n\n"
            f"支持的类型：\n"
            f"• 📝 文字消息\n"
            f"• 🖼️ 图片（可附带说明）\n"
            f"• 🎬 视频（可附带说明）\n"
            f"• 📎 文件\n"
            f"• 🎭 GIF动图\n\n"
            f"💡 提示：输入 /cancel_broadcast 取消",
            parse_mode=None,
            reply_markup=cancel_markup
        )
    except Exception as e:
        logger.error(f"发送提示消息失败: {e}")
        # 如果失败，尝试使用 HTML
        cancel_keyboard = [[InlineKeyboardButton("❌ 取消群发", callback_data="bc_cancel_and_exit")]]
        cancel_markup = InlineKeyboardMarkup(cancel_keyboard)

        await query.message.reply_text(
            f"📝 <b>确认发送配置</b>\n\n"
            f"{mode_text}\n"
            f"🎯 目标数量：{len(target_ids)} 个\n\n"
            f"👉 请输入要发送的消息内容：\n"
            f"(支持 Markdown，输入 /cancel_broadcast 取消)\n\n"
            f"💡 提示：直接输入文字开始群发，或点击下方按钮取消",
            parse_mode="HTML",
            reply_markup=cancel_markup  # 添加取消按钮
        )

    return BC_INPUT_MESSAGE
    
async def bc_send_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """发送给所有群组（支持分批提示）"""
    query = update.callback_query
    await query.answer()

    all_groups = context.user_data.get("bc_all_groups", [])
    selected_category = context.user_data.get("bc_selected_category", None)

    # 如果选择了分类，只统计该分类下的群组
    if selected_category and selected_category != "所有群组":
        all_groups = [g for g in all_groups if g.get('category', '未分类') == selected_category]

    total = len(all_groups)

    if total > 200:
        # 超过200个群，建议分批
        keyboard = [
            [InlineKeyboardButton("📦 分批发送 (每批200个)", callback_data="bc_batch_200")],
            [InlineKeyboardButton("🚀 全部发送 (耗时较长)", callback_data="bc_send_all_force")],
            [InlineKeyboardButton("❌ 取消", callback_data="bc_cancel")]
        ]
        await query.message.reply_text(
            f"⚠️ **提示：即将向 {total} 个群发送消息**\n\n"
            f"全部发送预计需要 {total * 2 / 60:.0f} 分钟\n"
            f"建议分批发送，避免超时",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return

    return await bc_prepare_send(update, context, "all")

async def bc_send_all_force(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """强制全部发送（不分批）"""
    query = update.callback_query
    await query.answer()
    return await bc_prepare_send(update, context, "all")

async def bc_send_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """发送给选中的群组"""
    return await bc_prepare_send(update, context, "selected")

async def bc_batch_send_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始分批发送"""
    query = update.callback_query
    await query.answer()

    all_groups = context.user_data.get("bc_all_groups", [])
    selected_category = context.user_data.get("bc_selected_category", None)

    # 如果选择了分类，只发送该分类下的群组
    if selected_category and selected_category != "所有群组":
        all_groups = [g for g in all_groups if g.get('category', '未分类') == selected_category]

    batch_size = 200
    batches = [all_groups[i:i+batch_size] for i in range(0, len(all_groups), batch_size)]

    context.user_data["bc_batches"] = batches
    context.user_data["bc_current_batch"] = 0
    context.user_data["bc_batch_results"] = {"success": 0, "failed": 0, "current": 0}

    await query.message.reply_text(
        f"📦 将分 {len(batches)} 批发送\n"
        f"每批最多 {batch_size} 个群，批次间隔5秒\n\n"
        f"总群组数：{len(all_groups)} 个\n\n"
        f"开始发送第一批？",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("▶️ 开始发送", callback_data="bc_start_batch")
        ]])
    )
    return BC_SELECT_GROUPS

async def bc_execute_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """执行分批发送"""
    query = update.callback_query
    await query.answer("开始发送...")

    batches = context.user_data.get("bc_batches", [])
    current_batch = context.user_data.get("bc_current_batch", 0)
    batch_results = context.user_data.get("bc_batch_results", {"success": 0, "failed": 0, "current": 0})
    message_text = context.user_data.get("bc_message_content", "")

    if not message_text:
        await query.message.reply_text("❌ 未找到消息内容，请重新开始")
        return end_conversation(update, context)

    if current_batch >= len(batches):
        await query.message.reply_text("✅ 所有批次已发送完成！")
        return await end_conversation(update, context)

    batch = batches[current_batch]
    progress_msg = await query.message.reply_text(
        f"📦 **批次 {current_batch + 1}/{len(batches)} 发送中...**\n"
        f"本批次群组数：{len(batch)}\n"
        f"已发送成功：{batch_results['success']} | 失败：{batch_results['failed']}"
    )

    success = 0
    failed = 0

    for i, group in enumerate(batch):
        gid = group["id"]
        delay = random.uniform(0.5, 1.5)
        await asyncio.sleep(delay)

        try:
            await context.bot.send_message(
                chat_id=gid, 
                text=message_text, 
                parse_mode="Markdown"
            )
            success += 1
            batch_results["success"] += 1
        except Exception as e:
            logger.error(f"发送失败 {gid}: {e}")
            failed += 1
            batch_results["failed"] += 1

        if (i + 1) % 20 == 0 or i == len(batch) - 1:
            try:
                await progress_msg.edit_text(
                    f"📦 **批次 {current_batch + 1}/{len(batches)} 发送中...**\n"
                    f"本批次进度：{i+1}/{len(batch)}\n"
                    f"✅ 成功：{success} | ❌ 失败：{failed}\n\n"
                    f"📊 **总计**\n"
                    f"✅ 成功：{batch_results['success']} | ❌ 失败：{batch_results['failed']}"
                )
            except:
                pass

    # 批次间隔
    if current_batch + 1 < len(batches):
        await progress_msg.edit_text(
            f"✅ **批次 {current_batch + 1} 完成！**\n"
            f"本批次：成功 {success}，失败 {failed}\n\n"
            f"等待5秒后开始下一批...\n"
            f"或点击「下一批」立即开始",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⏩ 下一批", callback_data="bc_next_batch")
            ]])
        )

        # 等待5秒或用户点击按钮
        context.user_data["bc_waiting_for_next"] = True
        await asyncio.sleep(5)

        if context.user_data.get("bc_waiting_for_next", False):
            context.user_data["bc_current_batch"] = current_batch + 1
            await bc_execute_batch(update, context)
    else:
        await progress_msg.edit_text(
            f"🎉 **所有批次发送完成！**\n\n"
            f"📊 **最终统计**\n"
            f"✅ 成功：{batch_results['success']}\n"
            f"❌ 失败：{batch_results['failed']}\n"
            f"📦 总群组数：{batch_results['success'] + batch_results['failed']}"
        )
        return await end_conversation(update, context)

async def bc_next_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """手动开始下一批"""
    query = update.callback_query
    await query.answer()

    context.user_data["bc_waiting_for_next"] = False
    current_batch = context.user_data.get("bc_current_batch", 0)
    context.user_data["bc_current_batch"] = current_batch + 1
    await bc_execute_batch(update, context)

# --- 状态 2: 输入消息 ---
async def receive_message_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收消息输入（支持文字、图片、视频、文件）"""
    message = update.message
    user_id = update.effective_user.id
    # 读取用户设置的默认附言
    from db import get_user_preferences
    prefs = get_user_preferences(user_id)
    signature = prefs.get("broadcast_signature", "")

    # 调试日志
    logger.info(f"收到消息输入: text={message.text}, photo={bool(message.photo)}, video={bool(message.video)}")

    # 检查是否是取消命令
    if message.text and message.text.strip() == "/cancel_broadcast":
        keys = ["bc_all_groups", "bc_selected_ids", "bc_message_content", "bc_temp_target_ids",
                "bc_selected_category", "bc_batches", "bc_current_batch", "bc_batch_results",
                "bc_waiting_for_next", "bc_current_page"]
        for k in keys:
            context.user_data.pop(k, None)
        context.user_data.pop("active_module", None)
        from handlers.menu import get_main_menu
        await update.message.reply_text("❌ 已取消，返回主菜单", reply_markup=get_main_menu(user_id))
        return ConversationHandler.END

    # 存储消息内容（支持多种类型）
    message_data = {}

    # 文字消息
    if message.text:
        message_data["type"] = "text"
        content = message.text
        if signature:
            content += "\n附言：" + signature
        message_data["content"] = content
        logger.info(f"检测到文字消息: {message.text[:50]}")
    # 图片消息
    elif message.photo:
        message_data["type"] = "photo"
        # 取最大尺寸的图片
        photo = message.photo[-1]
        message_data["file_id"] = photo.file_id
        caption = message.caption or ""
        if signature:
            caption = caption + "\n附言：" + signature if caption else signature
        message_data["caption"] = caption
        logger.info(f"检测到图片消息, file_id: {photo.file_id[:20]}...")
    # 视频消息
    elif message.video:
        message_data["type"] = "video"
        message_data["file_id"] = message.video.file_id
        caption = message.caption or ""
        if signature:
            caption = caption + "\n附言：" + signature if caption else signature
        message_data["caption"] = caption
        logger.info(f"检测到视频消息, file_id: {message.video.file_id[:20]}...")
    # 文档/文件消息
    elif message.document:
        message_data["type"] = "document"
        message_data["file_id"] = message.document.file_id
        caption = message.caption or ""
        if signature:
            caption = caption + "\n附言：" + signature if caption else signature
        message_data["caption"] = caption
        message_data["filename"] = message.document.file_name
        logger.info(f"检测到文件消息: {message.document.file_name}")
    # 动画/GIF消息
    elif message.animation:
        message_data["type"] = "animation"
        message_data["file_id"] = message.animation.file_id
        caption = message.caption or ""
        if signature:
            caption = caption + "\n附言：" + signature if caption else signature
        message_data["caption"] = caption
        logger.info(f"检测到GIF消息")
    # 音频消息
    elif message.audio:
        message_data["type"] = "audio"
        message_data["file_id"] = message.audio.file_id
        caption = message.caption or ""
        if signature:
            caption = caption + "\n附言：" + signature if caption else signature
        message_data["caption"] = caption
        logger.info(f"检测到音频消息")
    # 贴纸消息
    elif message.sticker:
        message_data["type"] = "sticker"
        message_data["file_id"] = message.sticker.file_id
        logger.info(f"检测到贴纸消息")
    else:
        await update.message.reply_text("❌ 不支持此消息类型，请发送文字、图片、视频或文件")
        return BC_INPUT_MESSAGE

    # 保存消息数据
    context.user_data["bc_message_data"] = message_data
    count = len(context.user_data.get("bc_temp_target_ids", []))

    # 显示预览 - 根据不同类型显示实际内容
    keyboard = [
        [InlineKeyboardButton("🚀 确认发送", callback_data="bc_exec_confirm")],
        [InlineKeyboardButton("✏️ 重新输入", callback_data="bc_reinput")],
        [InlineKeyboardButton("❌ 取消群发", callback_data="bc_cancel_and_exit")]
    ]

    if message_data["type"] == "text":
        # 文字消息：显示文字内容
        preview = message_data["content"][:200] + "..." if len(message_data["content"]) > 200 else message_data["content"]
        await update.message.reply_text(
            f"📋 **发送预览**\n\n"
            f"类型：文字\n\n"
            f"内容：\n{preview}\n\n"
            f"🎯 目标数量：{count} 个群\n\n"
            f"✅ 确认发送吗？",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif message_data["type"] == "photo":
        # 图片消息：发送图片预览 + 说明
        caption = f"📋 **发送预览**\n\n类型：图片\n"
        if message_data['caption']:
            caption += f"说明：{message_data['caption'][:100]}\n"
        caption += f"\n🎯 目标数量：{count} 个群\n\n✅ 确认发送吗？"

        await update.message.reply_photo(
            photo=message_data["file_id"],
            caption=caption,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif message_data["type"] == "video":
        # 视频消息：发送视频预览 + 说明
        caption = f"📋 **发送预览**\n\n类型：视频\n"
        if message_data['caption']:
            caption += f"说明：{message_data['caption'][:100]}\n"
        caption += f"\n🎯 目标数量：{count} 个群\n\n✅ 确认发送吗？"

        await update.message.reply_video(
            video=message_data["file_id"],
            caption=caption,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif message_data["type"] == "document":
        # 文件消息：发送文件预览
        caption = f"📋 **发送预览**\n\n类型：文件\n文件名：{message_data.get('filename', '未知')}\n"
        if message_data['caption']:
            caption += f"说明：{message_data['caption'][:100]}\n"
        caption += f"\n🎯 目标数量：{count} 个群\n\n✅ 确认发送吗？"

        await update.message.reply_document(
            document=message_data["file_id"],
            caption=caption,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif message_data["type"] == "animation":
        # GIF动图：发送GIF预览
        caption = f"📋 **发送预览**\n\n类型：GIF动图\n"
        if message_data['caption']:
            caption += f"说明：{message_data['caption'][:100]}\n"
        caption += f"\n🎯 目标数量：{count} 个群\n\n✅ 确认发送吗？"

        await update.message.reply_animation(
            animation=message_data["file_id"],
            caption=caption,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif message_data["type"] == "audio":
        # 音频消息
        caption = f"📋 **发送预览**\n\n类型：音频\n"
        if message_data['caption']:
            caption += f"说明：{message_data['caption'][:100]}\n"
        caption += f"\n🎯 目标数量：{count} 个群\n\n✅ 确认发送吗？"

        await update.message.reply_audio(
            audio=message_data["file_id"],
            caption=caption,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif message_data["type"] == "sticker":
        # 贴纸消息
        caption = f"📋 **发送预览**\n\n类型：贴纸\n\n🎯 目标数量：{count} 个群\n\n✅ 确认发送吗？"

        await update.message.reply_sticker(
            sticker=message_data["file_id"],
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        # 贴纸不能带 caption，单独发送文字确认
        await update.message.reply_text(
            caption,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    return BC_CONFIRM_SEND

async def bc_reinput(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """重新输入消息"""
    query = update.callback_query
    await query.answer()
    # 清除之前的消息数据
    context.user_data.pop("bc_message_data", None)
    await query.message.reply_text(
        "👉 **请重新发送要群发的内容**\n\n"
        "支持：\n"
        "• 文字消息\n"
        "• 图片\n"
        "• 视频\n"
        "• 文件\n"
        "• GIF动图\n\n"
        "💡 提示：图片/视频可以附带说明文字"
    )
    return BC_INPUT_MESSAGE

# --- 状态 3: 执行发送 ---
async def execute_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """执行群发 - 支持多种消息类型"""
    query = update.callback_query
    await query.answer("任务启动...")

    target_ids = context.user_data.get("bc_temp_target_ids", [])
    message_data = context.user_data.get("bc_message_data", {})

    if not target_ids or not message_data:
        await query.message.reply_text("❌ 数据异常，请重新开始。")
        return await end_conversation(update, context)

    total = len(target_ids)

    # 根据群组数量自动调整策略
    if total > 300:
        batch_size = 30
        delay_between = 2
        delay_in_batch = 0.3
    elif total > 100:
        batch_size = 20
        delay_between = 1
        delay_in_batch = 0.5
    else:
        batch_size = 15
        delay_between = 0.5
        delay_in_batch = 0.8

    progress_msg = await query.message.reply_text(
        f"🚀 **群发进行中...**\n"
        f"总群组：{total} 个\n"
        f"消息类型：{message_data['type']}\n"
        f"策略：每批{batch_size}个，共{ (total + batch_size - 1) // batch_size }批\n"
        f"进度：0 / {total}"
    )

    success = 0
    failed = 0

    async def send_one(gid):
        """发送单条消息，自动处理频控重试"""
        retries = 3
        for attempt in range(retries):
            try:
                msg_type = message_data["type"]
                if msg_type == "text":
                    await context.bot.send_message(
                        chat_id=gid,
                        text=message_data["content"],
                        parse_mode="Markdown"
                    )
                elif msg_type == "photo":
                    await context.bot.send_photo(
                        chat_id=gid,
                        photo=message_data["file_id"],
                        caption=message_data.get("caption", "")
                    )
                elif msg_type == "video":
                    await context.bot.send_video(
                        chat_id=gid,
                        video=message_data["file_id"],
                        caption=message_data.get("caption", "")
                    )
                elif msg_type == "document":
                    await context.bot.send_document(
                        chat_id=gid,
                        document=message_data["file_id"],
                        caption=message_data.get("caption", "")
                    )
                elif msg_type == "animation":
                    await context.bot.send_animation(
                        chat_id=gid,
                        animation=message_data["file_id"],
                        caption=message_data.get("caption", "")
                    )
                elif msg_type == "audio":
                    await context.bot.send_audio(
                        chat_id=gid,
                        audio=message_data["file_id"],
                        caption=message_data.get("caption", "")
                    )
                elif msg_type == "sticker":
                    await context.bot.send_sticker(
                        chat_id=gid,
                        sticker=message_data["file_id"]
                    )
                return True
            except RetryAfter as e:
                wait_time = e.retry_after
                logger.warning(f"发送到 {gid} 触发频控，等待 {wait_time} 秒后重试 (尝试 {attempt+1}/{retries})")
                await asyncio.sleep(wait_time)
                # 继续重试
            except (TimedOut, NetworkError) as e:
                logger.warning(f"发送到 {gid} 网络错误: {e}，重试 {attempt+1}/{retries}")
                await asyncio.sleep(2 ** attempt)  # 指数退避
            except Exception as e:
                logger.error(f"发送到 {gid} 失败: {e}")
                return False
        return False

    # 分批发送
    for batch_start in range(0, total, batch_size):
        batch = target_ids[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (total + batch_size - 1) // batch_size

        # 并发发送这一批
        results = await asyncio.gather(*[send_one(gid) for gid in batch])

        batch_success = sum(results)
        batch_failed = len(batch) - batch_success
        success += batch_success
        failed += batch_failed

        # 更新进度
        await progress_msg.edit_text(
            f"🚀 **群发进行中...**\n"
            f"批次 {batch_num}/{total_batches}\n"
            f"进度：{batch_start + len(batch)} / {total}\n"
            f"✅ 成功：{success} | ❌ 失败：{failed}\n"
            f"⏱️ 等待 {delay_between} 秒..."
        )

        # 批次间延迟
        if batch_start + batch_size < total:
            await asyncio.sleep(delay_between)

    result_text = (
        f"🎉 **群发完成！**\n\n"
        f"总计：{total} 个群\n"
        f"消息类型：{message_data['type']}\n"
        f"✅ 成功：{success}\n"
        f"❌ 失败：{failed}\n\n"
        f"💡 失败原因通常是机器人已被移出该群"
    )

    await progress_msg.edit_text(result_text)
    return await end_conversation(update, context)

# --- 辅助函数 ---
async def end_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """结束对话并清理数据"""
    # 获取 user_id
    if update.callback_query:
        user_id = update.callback_query.from_user.id
    else:
        user_id = update.effective_user.id

    # 清理所有广播相关数据
    keys = ["bc_all_groups", "bc_selected_ids", "bc_message_content", "bc_temp_target_ids",
            "bc_selected_category", "bc_batches", "bc_current_batch", "bc_batch_results",
            "bc_waiting_for_next", "bc_current_state", "in_broadcast", "bc_current_page"]
    for k in keys:
        if k in context.user_data:
            context.user_data.pop(k, None)

    # 返回主菜单
    from handlers.menu import get_main_menu

    try:
        if update.callback_query and update.callback_query.message:
            # 改为发送新消息，然后删除原内联键盘消息
            await update.callback_query.message.reply_text(
                "请选择功能：",
                reply_markup=get_main_menu(user_id)
            )
            try:
                await update.callback_query.message.delete()
            except Exception:
                pass
        elif update.message:
            await update.message.reply_text(
                "请选择功能：",
                reply_markup=get_main_menu(user_id)
            )
        elif update.effective_chat:
            await update.effective_chat.send_message(
                "请选择功能：",
                reply_markup=get_main_menu(user_id)
            )
    except Exception as e:
        logger.error(f"返回主菜单失败: {e}")
        # 降级方案：如果 reply 也失败，尝试直接发送
        if update.callback_query and update.callback_query.message:
            await update.callback_query.message.reply_text(
                "请选择功能：",
                reply_markup=get_main_menu(user_id)
            )
            try:
                await update.callback_query.message.delete()
            except Exception:
                pass

    return ConversationHandler.END

async def bc_cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消广播"""
    query = update.callback_query
    await query.answer("已取消")
    context.user_data.pop("bc_current_page", None)
    return await end_conversation(update, context)

# 添加 fallback 处理器
async def bc_fallback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理未预期的消息，清理并返回主菜单"""
    logger.info(f"广播模块 fallback 被触发")

    # 确定 user_id
    if update.callback_query:
        user_id = update.callback_query.from_user.id
    else:
        user_id = update.effective_user.id

    # 检查是否正在等待输入消息
    if context.user_data.get("bc_temp_target_ids") and not context.user_data.get("bc_message_data"):
        # 如果还在等待输入，不清理，只提示
        if update.message:
            await update.message.reply_text(
                "📝 请发送要群发的内容（文字、图片、视频等）\n"
                "或输入 /cancel_broadcast 取消"
            )
        return ConversationHandler.END

    # 清理所有数据
    keys = ["bc_all_groups", "bc_selected_ids", "bc_message_content", "bc_temp_target_ids",
            "bc_selected_category", "bc_batches", "bc_current_batch", "bc_batch_results",
            "bc_waiting_for_next", "bc_current_page", "bc_message_data"]
    for k in keys:
        context.user_data.pop(k, None)

    from handlers.menu import get_main_menu
    try:
        if update.callback_query:
            # 修改为 reply_text + 删除原消息
            await update.callback_query.message.reply_text(
                "请选择功能：",
                reply_markup=get_main_menu(user_id)
            )
            try:
                await update.callback_query.message.delete()
            except Exception:
                pass
        elif update.message:
            await update.message.reply_text(
                "请选择功能：",
                reply_markup=get_main_menu(user_id)
            )
    except Exception as e:
        logger.error(f"返回主菜单失败: {e}")

    return ConversationHandler.END

async def bc_force_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """强制清理广播状态"""
    query = update.callback_query
    await query.answer()

    # 清理所有数据
    keys = ["bc_all_groups", "bc_selected_ids", "bc_message_content", "bc_temp_target_ids",
            "bc_selected_category", "bc_batches", "bc_current_batch", "bc_batch_results",
            "bc_waiting_for_next", "bc_current_page"]
    for k in keys:
        context.user_data.pop(k, None)

    from handlers.menu import get_main_menu
    await query.message.reply_text(
        "请选择功能：",
        reply_markup=get_main_menu(user_id)
    )
    try:
        await query.message.delete()
    except Exception:
        pass
    return ConversationHandler.END

# 🔥 添加统一的取消命令处理器
# broadcast.py - 修复 bc_cancel_command

async def bc_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """统一的取消命令处理器"""
    print(f"[DEBUG] bc_cancel_command 被调用")
    print(f"[DEBUG] 清理前 context.user_data: {context.user_data}")

    # 清理所有数据
    keys = ["bc_all_groups", "bc_selected_ids", "bc_message_content", "bc_temp_target_ids",
            "bc_selected_category", "bc_batches", "bc_current_batch", "bc_batch_results",
            "bc_waiting_for_next", "bc_current_state", "in_broadcast", "bc_current_page"]
    for k in keys:
        if k in context.user_data:
            context.user_data.pop(k, None)

    print(f"[DEBUG] 清理后 context.user_data: {context.user_data}")

    # 🔥 重要：清除 ConversationHandler 的状态
    # 通过返回 ConversationHandler.END 来结束对话
    from handlers.menu import get_main_menu

    try:
        if update.callback_query:
            await update.callback_query.message.reply_text(
                "❌ 已取消群发\n\n请选择功能：",
                reply_markup=get_main_menu(user_id)
            )
            try:
                await update.callback_query.message.delete()
            except Exception:
                pass
        elif update.message:
            await update.message.reply_text(
                "❌ 已取消群发\n\n请选择功能：",
                reply_markup=get_main_menu(user_id)
            )
    except Exception as e:
        logger.error(f"取消操作失败: {e}")

    print(f"[DEBUG] bc_cancel_command 返回 ConversationHandler.END")
    return ConversationHandler.END

# broadcast.py - 确保有这个函数

async def bc_cancel_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """作为 ConversationHandler fallback 的取消处理"""
    print(f"[DEBUG] bc_cancel_fallback 被调用")

    # 确定 user_id
    if update.callback_query:
        user_id = update.callback_query.from_user.id
    else:
        user_id = update.effective_user.id

    # 发送提示消息
    try:
        if update.callback_query:
            await update.callback_query.message.reply_text("❌ 已取消群发功能")
        elif update.message:
            await update.message.reply_text("❌ 已取消群发功能")
    except Exception as e:
        logger.error(f"发送取消提示失败: {e}")

    # 清理所有数据
    keys = ["bc_all_groups", "bc_selected_ids", "bc_message_content", "bc_temp_target_ids",
            "bc_selected_category", "bc_batches", "bc_current_batch", "bc_batch_results",
            "bc_waiting_for_next", "bc_current_state", "in_broadcast", "bc_current_page"]
    for k in keys:
        if k in context.user_data:
            context.user_data.pop(k, None)

    # 发送取消消息
    from handlers.menu import get_main_menu

    try:
        if update.callback_query:
            await update.callback_query.message.reply_text(
                "❌ 已取消群发\n\n请选择功能：",
                reply_markup=get_main_menu(user_id)
            )
            try:
                await update.callback_query.message.delete()
            except Exception:
                pass
        elif update.message:
            await update.message.reply_text(
                "❌ 已取消群发\n\n请选择功能：",
                reply_markup=get_main_menu(user_id)
            )
    except Exception as e:
        logger.error(f"取消操作失败: {e}")
        # 如果编辑失败，尝试发送新消息
        if update.effective_chat:
            await update.effective_chat.send_message(
                "❌ 已取消群发\n\n请选择功能：",
                reply_markup=get_main_menu(user_id)
            )

    # 返回 END 结束对话
    return ConversationHandler.END

# --- 注册处理器 ---
def get_handlers():
    return [
        ConversationHandler(
            entry_points=[
                CallbackQueryHandler(start_broadcast, pattern="^(func_broadcast|broadcast|bc_start_real)$")
            ],
            states={
                BC_SELECT_GROUPS: [
                    CallbackQueryHandler(bc_toggle_group, pattern="^bc_toggle_"),
                    CallbackQueryHandler(bc_filter_by_category, pattern="^bc_filter_cat_"),
                    CallbackQueryHandler(bc_select_all, pattern="^bc_select_all$"),
                    CallbackQueryHandler(bc_deselect_all, pattern="^bc_deselect_all$"),
                    CallbackQueryHandler(bc_page_prev, pattern="^bc_page_prev$"),      # 新增
                    CallbackQueryHandler(bc_page_next, pattern="^bc_page_next$"),      # 新增
                    CallbackQueryHandler(bc_send_all, pattern="^bc_send_all$"),
                    CallbackQueryHandler(bc_send_all_force, pattern="^bc_send_all_force$"),
                    CallbackQueryHandler(bc_send_selected, pattern="^bc_send_selected$"),
                    CallbackQueryHandler(bc_batch_send_start, pattern="^bc_batch_200$"),
                    CallbackQueryHandler(bc_execute_batch, pattern="^bc_start_batch$"),
                    CallbackQueryHandler(bc_next_batch, pattern="^bc_next_batch$"),
                    CallbackQueryHandler(bc_back_to_main, pattern="^bc_back_to_main$"),
                    CallbackQueryHandler(bc_cancel_broadcast, pattern="^bc_cancel$"),
                    CallbackQueryHandler(bc_force_cleanup, pattern="^main_menu$"),
                    CallbackQueryHandler(bc_cancel_and_exit, pattern="^bc_cancel_and_exit$"),  # 新增
                ],
                BC_INPUT_MESSAGE: [
                    MessageHandler(~filters.COMMAND, receive_message_input),  # ← 改成处理所有非命令消息
                    CallbackQueryHandler(bc_cancel_and_exit, pattern="^bc_cancel_and_exit$"),
                ],
                BC_CONFIRM_SEND: [
                    CallbackQueryHandler(execute_broadcast, pattern="^bc_exec_confirm$"),
                    CallbackQueryHandler(bc_reinput, pattern="^bc_reinput$"),
                    CallbackQueryHandler(bc_back_to_main, pattern="^bc_back_to_main$"),  
                    CallbackQueryHandler(bc_cancel_broadcast, pattern="^bc_cancel$"),
                    CallbackQueryHandler(bc_cancel_and_exit, pattern="^bc_cancel_and_exit$"),  # 新增
                ],
            },
            fallbacks=[
                CommandHandler("cancel_broadcast", bc_cancel_fallback),
                MessageHandler(filters.ALL, bc_fallback_handler),
            ],
            per_message=False,
            allow_reentry=True,
        )
    ]
# handlers/broadcast.py - 添加键盘版

async def start_broadcast_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """群发功能 - 键盘版入口"""
    user_id = update.effective_user.id

    if not is_authorized(user_id, require_full_access=True):
        await update.message.reply_text("❌ 管理人/操作员才能使用，如需使用请联系 @ChinaEdward")
        return

    # 模拟点击群发按钮，触发原有的 inline 流程
    # 先设置必要的状态
    context.user_data["in_broadcast"] = True

    # 清理旧数据
    keys = ["bc_all_groups", "bc_selected_ids", "bc_message_content", "bc_temp_target_ids",
            "bc_selected_category", "bc_batches", "bc_current_batch", "bc_batch_results",
            "bc_waiting_for_next", "bc_current_state", "bc_current_page"]
    for k in keys:
        context.user_data.pop(k, None)

    from db import get_all_groups_from_db
    groups = get_all_groups_from_db()

    if not groups:
        await update.message.reply_text("⚠️ **未找到任何有效群组**\n\n请确保机器人已添加到群组中。")
        return

    context.user_data["bc_all_groups"] = groups
    context.user_data["bc_selected_ids"] = []

    # 使用内联按钮显示群组选择（和原有的 start_broadcast 一样）
    await show_group_selection_keyboard(update, context)


async def show_group_selection_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """群组选择 - 混合模式（键盘+内联）"""
    # 这里保持使用内联按钮来选择群组（因为群组列表很长，键盘不适合）
    # 只需要在底部添加返回主菜单的键盘即可
    await show_group_selection(update, context)
