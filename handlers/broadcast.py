import logging
import random
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackQueryHandler, MessageHandler, ConversationHandler, 
    ContextTypes, filters, CommandHandler
)
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

    if not is_authorized(user_id):
        await query.answer("❌ 无权限", show_alert=True)
        await query.message.reply_text("❌ 此功能仅限管理员或授权操作员使用。")
        return ConversationHandler.END

    await query.answer("正在检测群组状态...")

    groups = await sync_and_clean_groups(context)

    if not groups:
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

    # 如果选择了分类，筛选群组
    if selected_category and selected_category != "所有群组":
        groups = [g for g in groups if g.get('category', '未分类') == selected_category]

    total_count = len(groups)
    selected_count = len([g for g in groups if g['id'] in selected_ids])

    text = f"📢 **群发任务设置**\n\n"
    text += f"📊 当前显示：**{total_count}** 个群\n"
    if selected_category and selected_category != "所有群组":
        text += f"🏷️ 分类筛选：**{selected_category}**\n"
    text += f"✅ 已勾选：**{selected_count}** 个\n\n"
    text += "👇 **点击群名勾选/取消** (支持多选)："

    keyboard = []

    # 添加分类筛选按钮
    categories = get_all_categories()
    if categories:
        cat_row = []
        # 添加"所有群组"按钮
        cat_row.append(InlineKeyboardButton("🌍 所有群组", callback_data="bc_filter_cat_all"))

        for cat in categories:
            cat_name = cat['name']
            is_active = (selected_category == cat_name)
            icon = "✅" if is_active else "📁"
            cat_row.append(InlineKeyboardButton(f"{icon} {cat_name[:10]}", callback_data=f"bc_filter_cat_{cat_name}"))

        # 分两行显示（如果按钮太多）
        if len(cat_row) > 4:
            keyboard.append(cat_row[:4])
            keyboard.append(cat_row[4:])
        else:
            keyboard.append(cat_row)

    # 显示群组列表
    display_limit = 40
    display_groups = groups[:display_limit]

    if len(groups) > display_limit:
        text += f"\n_(仅显示前 {display_limit} 个，建议使用全选或筛选)_"

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

    # 底部按钮
    nav_row = [
        InlineKeyboardButton("✅ 全选当前", callback_data="bc_select_all"),
        InlineKeyboardButton("🚫 清空", callback_data="bc_deselect_all")
    ]

    send_row = [
        InlineKeyboardButton("🚀 全部发送", callback_data="bc_send_all"),
        InlineKeyboardButton("📤 发送选中", callback_data="bc_send_selected")
    ]

    keyboard.append(nav_row)
    keyboard.append(send_row)
    # 改为返回主菜单按钮
    keyboard.append([InlineKeyboardButton("◀️ 返回主菜单", callback_data="bc_back_to_main")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        if update.callback_query and update.callback_query.message:
            await update.callback_query.edit_message_text(
                text, parse_mode="Markdown", reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"编辑消息失败：{e}")

async def bc_back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """返回主菜单并结束对话"""
    query = update.callback_query
    await query.answer()

    # 清理所有广播相关的临时数据
    keys = ["bc_all_groups", "bc_selected_ids", "bc_message_content", "bc_temp_target_ids",
            "bc_selected_category", "bc_batches", "bc_current_batch", "bc_batch_results",
            "bc_waiting_for_next"]
    for k in keys:
        context.user_data.pop(k, None)

    # 返回主菜单
    from handlers.menu import get_main_menu
    await query.message.edit_text(
        "请选择功能：",
        reply_markup=get_main_menu()
    )
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
    """全选当前显示的群组"""
    query = update.callback_query
    await query.answer("已全选")

    groups = context.user_data.get("bc_all_groups", [])
    selected_category = context.user_data.get("bc_selected_category", None)

    # 只全选当前筛选条件下的群组
    if selected_category and selected_category != "所有群组":
        groups = [g for g in groups if g.get('category', '未分类') == selected_category]

    context.user_data["bc_selected_ids"] = [g["id"] for g in groups]
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
        mode_text = "✅ 模式：**全部群组** (无视勾选)"
    else:
        if not current_selected:
            await query.message.reply_text("⚠️ 您未勾选任何群组！\n请先勾选或直接点击'全部发送'。")
            return BC_SELECT_GROUPS
        target_ids = current_selected
        mode_text = "✅ 模式：**仅选中群组**"

    # 临时存储目标 ID
    context.user_data["bc_temp_target_ids"] = target_ids

    await query.message.reply_text(
        f"📝 **确认发送配置**\n\n"
        f"{mode_text}\n"
        f"🎯 目标数量：**{len(target_ids)}** 个\n\n"
        f"👉 **请输入要发送的消息内容：**\n"
        f"(支持 Markdown，输入 /cancel 取消)",
        parse_mode="Markdown"
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
        return end_conversation(update, context)

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
        return end_conversation(update, context)

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
    text = update.message.text.strip()
    if text == "/cancel":
        # 清理数据
        keys = ["bc_all_groups", "bc_selected_ids", "bc_message_content", "bc_temp_target_ids",
                "bc_selected_category", "bc_batches", "bc_current_batch", "bc_batch_results",
                "bc_waiting_for_next"]
        for k in keys:
            context.user_data.pop(k, None)

        # 返回主菜单
        from handlers.menu import get_main_menu
        await update.message.reply_text(
            "❌ 已取消，返回主菜单",
            reply_markup=get_main_menu()
        )
        return ConversationHandler.END

    context.user_data["bc_message_content"] = text
    count = len(context.user_data.get("bc_temp_target_ids", []))

    keyboard = [
        [InlineKeyboardButton("🚀 确认发送", callback_data="bc_exec_confirm")],
        [InlineKeyboardButton("✏️ 重新输入", callback_data="bc_reinput")]
    ]

    preview = text[:60] + "..." if len(text) > 60 else text

    await update.message.reply_text(
        f"📋 **发送预览**\n\n"
        f"{preview}\n\n"
        f"目标数：{count}\n"
        f"⏱️ 策略：随机间隔 0.5-1.5 秒",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return BC_CONFIRM_SEND

async def bc_reinput(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("👉 **请重新输入消息内容：**")
    return BC_INPUT_MESSAGE

# --- 状态 3: 执行发送 ---

async def execute_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("任务启动...")

    target_ids = context.user_data.get("bc_temp_target_ids", [])
    message_text = context.user_data.get("bc_message_content", "")

    if not target_ids or not message_text:
        await query.message.reply_text("❌ 数据异常，请重新开始。")
        return end_conversation(update, context)

    progress_msg = await query.message.reply_text(
        f"🚀 **群发进行中...**\n"
        f"进度：0 / {len(target_ids)}\n"
        f"✅ 成功：0 | ❌ 失败：0"
    )

    success = 0
    failed = 0
    total = len(target_ids)

    # 根据群组数量动态调整
    if total > 500:
        delay_range = (0.5, 1.0)
        batch_size = 50
    else:
        delay_range = (0.8, 1.5)
        batch_size = 20

    for i, gid in enumerate(target_ids):
        delay = random.uniform(*delay_range)
        await asyncio.sleep(delay)

        try:
            await context.bot.send_message(
                chat_id=gid, 
                text=message_text, 
                parse_mode="Markdown"
            )
            success += 1
        except Exception as e:
            logger.error(f"发送失败 {gid}: {e}")
            failed += 1

        if (i + 1) % batch_size == 0 or i == total - 1:
            try:
                remaining_seconds = (total - i - 1) * ((delay_range[0] + delay_range[1]) / 2)
                await progress_msg.edit_text(
                    f"🚀 **群发进行中...**\n"
                    f"进度：{i+1} / {total}\n"
                    f"✅ 成功：{success} | ❌ 失败：{failed}\n"
                    f"⏱️ 预计剩余：{remaining_seconds:.0f}秒"
                )
            except:
                pass

    result_text = (
        f"🎉 **任务完成!**\n\n"
        f"总计：{total}\n"
        f"✅ 成功：{success}\n"
        f"❌ 失败：{failed}\n\n"
        f"失败原因通常是机器人已被移出该群。"
    )

    try:
        await progress_msg.edit_text(result_text)
    except:
        await query.message.reply_text(result_text)

    return end_conversation(update, context)

# --- 辅助函数 ---


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
                    CallbackQueryHandler(bc_send_all, pattern="^bc_send_all$"),
                    CallbackQueryHandler(bc_send_all_force, pattern="^bc_send_all_force$"),
                    CallbackQueryHandler(bc_send_selected, pattern="^bc_send_selected$"),
                    CallbackQueryHandler(bc_batch_send_start, pattern="^bc_batch_200$"),
                    CallbackQueryHandler(bc_execute_batch, pattern="^bc_start_batch$"),
                    CallbackQueryHandler(bc_next_batch, pattern="^bc_next_batch$"),
                    CallbackQueryHandler(bc_back_to_main, pattern="^bc_back_to_main$"),  # 新增
                ],
                BC_INPUT_MESSAGE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, receive_message_input),
                    CommandHandler("cancel", bc_back_to_main),
                ],
                BC_CONFIRM_SEND: [
                    CallbackQueryHandler(execute_broadcast, pattern="^bc_exec_confirm$"),
                    CallbackQueryHandler(bc_reinput, pattern="^bc_reinput$"),
                    CallbackQueryHandler(bc_back_to_main, pattern="^bc_back_to_main$"),  # 新增
                ],
            },
            fallbacks=[CommandHandler("cancel", bc_back_to_main)],
            per_message=False,
        )
    ]
