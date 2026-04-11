# main.py - 修正后的版本

import asyncio
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler,
    ChatMemberHandler
)
from config import BOT_TOKEN
from auth import is_authorized, init_operators_from_db
from db import init_db, save_group, delete_group_from_db, DB_PATH
from handlers.start import start
from handlers import monitor,operator, usdt, accounting, broadcast, transfer
from handlers.git_update import get_git_handlers
from handlers.group_manager import (
    group_manager_menu, show_stats, list_categories, 
    add_category_start, delete_category_start, 
    delete_category_confirm, set_group_category_start,
    select_group_for_category, set_group_category,
    handle_text_input
)
from handlers.menu import get_main_menu
# 新增：监听群组成员加入/退出的服务消息（更可靠的方式）
from handlers.accounting import get_service_message_handler
from handlers.ai_client import get_ai_client

# 按钮路由处理器
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    print(f"[DEBUG] button_router 收到: {query.data}")

    # ========== 优先处理监控模块按钮（让 ConversationHandler 也能处理） ==========
    if query.data == "monitor_add":
        print(f"[DEBUG] 监控模块: 添加地址")
        from handlers import monitor
        await monitor.monitor_add_start(update, context)
        return

    if query.data == "monitor_remove":
        print(f"[DEBUG] 监控模块: 删除地址")
        from handlers import monitor
        await monitor.monitor_remove_start(update, context)
        return

    if query.data.startswith("monitor_del_"):
        print(f"[DEBUG] 监控模块: 确认删除")
        from handlers import monitor
        await monitor.monitor_remove_confirm(update, context)
        return

    if query.data == "monitor_list":
        print(f"[DEBUG] 监控模块: 查看列表")
        from handlers import monitor
        await monitor.monitor_list(update, context)
        return

    if query.data == "monitor_stats":
        print(f"[DEBUG] 监控模块: 月度统计")
        from handlers import monitor
        await monitor.monitor_stats(update, context)
        return

    if query.data == "monitor_menu":
        print(f"[DEBUG] 监控模块: 主菜单")
        from handlers import monitor
        await monitor.monitor_menu(update, context)
        return

    # ========== 先处理广播按钮 ==========
    if query.data == "broadcast":
        print(f"[DEBUG] 触发广播功能")
        from handlers.broadcast import start_broadcast
        await start_broadcast(update, context)
        return

    # ========== 处理群组管理菜单 ==========
    if query.data == "group_manager":
        await group_manager_menu(update, context)
        return

    # ========== 处理群组管理的子菜单 ==========
    if query.data == "gm_stats":
        await show_stats(update, context)
        return

    if query.data == "gm_list_cats":
        await list_categories(update, context)
        return

    if query.data == "gm_add_cat":
        await add_category_start(update, context)
        return

    if query.data == "gm_del_cat":
        await delete_category_start(update, context)
        return

    if query.data.startswith("del_cat_"):
        await delete_category_confirm(update, context)
        return

    if query.data == "gm_set_cat":
        await set_group_category_start(update, context)
        return

    if query.data.startswith("sel_group_"):
        await select_group_for_category(update, context)
        return

    if query.data.startswith("set_cat_"):
        await set_group_category(update, context)
        return

    if query.data == "refresh_group_list":
        from handlers.group_manager import show_group_list_page
        await show_group_list_page(update, context)
        return

    if query.data == "group_page_prev" or query.data == "group_page_next":
        from handlers.group_manager import handle_group_pagination
        await handle_group_pagination(update, context)
        return

    if query.data == "filter_uncategorized" or query.data == "filter_categorized":
        from handlers.group_manager import handle_group_pagination
        await handle_group_pagination(update, context)
        return

    # ========== 处理返回主菜单 ==========
    if query.data == "main_menu":
        await query.message.edit_text(
            "请选择功能：",
            reply_markup=get_main_menu()
        )
        return

    # ========== 处理互转查询返回主菜单 ==========
    if query.data == "transfer_back_to_main":
        from handlers.transfer import transfer_back_to_main
        await transfer_back_to_main(update, context)
        return

    # 在 button_router 函数中，添加记账模块的按钮处理
    # ========== 处理记账模块按钮 ==========
    if query.data == "acct_current":
        from handlers.accounting import handle_current_bill
        class FakeMessage:
            def __init__(self, chat_id, user_id):
                self.chat = type('obj', (object,), {'id': chat_id, 'type': 'group'})()
                self.from_user = type('obj', (object,), {'id': user_id})()
                self.text = "当前账单"
        fake_msg = FakeMessage(query.message.chat.id, query.from_user.id)
        update.message = fake_msg
        await handle_current_bill(update, context)
        return

    if query.data == "acct_today":
        from handlers.accounting import handle_today_stats
        class FakeMessage:
            def __init__(self, chat_id, user_id):
                self.chat = type('obj', (object,), {'id': chat_id, 'type': 'group'})()
                self.from_user = type('obj', (object,), {'id': user_id})()
                self.text = "今日总"
        fake_msg = FakeMessage(query.message.chat.id, query.from_user.id)
        update.message = fake_msg
        await handle_today_stats(update, context)
        return

    if query.data == "acct_total":
        from handlers.accounting import handle_total_stats
        class FakeMessage:
            def __init__(self, chat_id, user_id):
                self.chat = type('obj', (object,), {'id': chat_id, 'type': 'group'})()
                self.from_user = type('obj', (object,), {'id': user_id})()
                self.text = "总"
        fake_msg = FakeMessage(query.message.chat.id, query.from_user.id)
        update.message = fake_msg
        await handle_total_stats(update, context)
        return

    if query.data == "acct_query":
        from handlers.accounting import handle_query_bill
        class FakeMessage:
            def __init__(self, chat_id, user_id):
                self.chat = type('obj', (object,), {'id': chat_id, 'type': 'group'})()
                self.from_user = type('obj', (object,), {'id': user_id})()
                self.text = "查询账单"
        fake_msg = FakeMessage(query.message.chat.id, query.from_user.id)
        update.message = fake_msg
        await handle_query_bill(update, context)
        return

    if query.data == "acct_clear":
        from handlers.accounting import handle_clear_bill
        class FakeMessage:
            def __init__(self, chat_id, user_id):
                self.chat = type('obj', (object,), {'id': chat_id, 'type': 'group'})()
                self.from_user = type('obj', (object,), {'id': user_id})()
                self.text = "清理账单"
        fake_msg = FakeMessage(query.message.chat.id, query.from_user.id)
        update.message = fake_msg
        await handle_clear_bill(update, context)
        return

    if query.data == "acct_clear_all":
        from handlers.accounting import handle_clear_all_bill
        class FakeMessage:
            def __init__(self, chat_id, user_id):
                self.chat = type('obj', (object,), {'id': chat_id, 'type': 'group'})()
                self.from_user = type('obj', (object,), {'id': user_id})()
                self.text = "清理总账单"
        fake_msg = FakeMessage(query.message.chat.id, query.from_user.id)
        update.message = fake_msg
        await handle_clear_all_bill(update, context)
        return

    if query.data == "acct_help":
        from handlers.accounting import handle
        await handle(update, context)
        return

    # ========== 处理记账模块的日期选择和确认按钮 ==========
    if query.data.startswith("acct_date_"):
        from handlers.accounting import handle_date_selection
        await handle_date_selection(update, context)
        return

    if query.data == "acct_cancel":
        await query.message.edit_text("✅ 已取消查询")
        return

    # ========== 处理清理账单确认按钮 ==========
    if query.data == "clear_current_confirm":
        from handlers.accounting import handle_clear_current_confirm
        await handle_clear_current_confirm(update, context)
        return

    if query.data == "clear_current_cancel":
        from handlers.accounting import handle_clear_current_cancel
        await handle_clear_current_cancel(update, context)
        return

    if query.data == "clear_all_confirm":
        from handlers.accounting import handle_clear_all_confirm
        await handle_clear_all_confirm(update, context)
        return

    if query.data == "clear_all_cancel":
        from handlers.accounting import handle_clear_all_cancel
        await handle_clear_all_cancel(update, context)
        return

    # ========== 权限检查 ==========
    if not is_authorized(user_id):
        await query.message.reply_text("❌ 管理人/操作员才能使用，如需使用请联系 @ChinaEdward")
        return

    data = query.data

    if data in ["func_broadcast", "broadcast", "bc_start_real"]:
        return None

    if data == "operator":
        context.user_data["active_module"] = "operator"
        await operator.handle(update, context)
        return

    if data.startswith("op_"):
        context.user_data["active_module"] = "operator"
        await operator.handle_buttons(update, context)
        return

    if data == "usdt":
        context.user_data["active_module"] = "usdt"
        await usdt.handle(update, context)
        return

    if data == "transfer":
        await transfer.show_transfer_menu(update, context)
        return

    if data == "accounting":
        context.user_data["active_module"] = "accounting"
        await accounting.handle(update, context)
        return

    print(f"Unhandled callback data: {data}")

async def extract_address_from_text(text: str) -> str:
    """从用户消息中提取地址（支持备注名称）"""
    import re
    from db import get_monitored_addresses

    print(f"[DEBUG] extract_address_from_text 收到文本: {text}")

    # 先尝试匹配 TRC20 地址格式
    trc20_pattern = r'T[0-9A-Za-z]{33}'
    match = re.search(trc20_pattern, text)
    if match:
        print(f"[DEBUG] 匹配到地址: {match.group()}")
        return match.group()

    # 获取所有监控地址
    addresses = get_monitored_addresses()
    print(f"[DEBUG] 监控地址数量: {len(addresses)}")

    if not addresses:
        print(f"[DEBUG] 没有监控地址")
        return None

    # 方法1：去除干扰词后匹配
    clean_text = text
    remove_words = ["帮我", "分析", "监听", "地址", "今日", "本周", "本月", "收支", "情况", "的", "一下"]
    for word in remove_words:
        clean_text = clean_text.replace(word, "")
    clean_text = clean_text.strip()
    print(f"[DEBUG] 清理后文本: {clean_text}")

    if clean_text:
        for addr in addresses:
            note = addr.get('note', '')
            print(f"[DEBUG] 检查备注: {note}")
            if note and (clean_text == note or clean_text in note or note in clean_text):
                print(f"[DEBUG] 匹配到备注: {note}, 地址: {addr['address']}")
                return addr['address']

    # 方法2：使用正则提取中文备注名
    patterns = [
        r'([\u4e00-\u9fa5]{2,})的?地址',
        r'([\u4e00-\u9fa5]{2,})监听地址',
        r'分析([\u4e00-\u9fa5]{2,})',
        r'([\u4e00-\u9fa5]{2,})的?收支',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            possible_note = match.group(1)
            print(f"[DEBUG] 正则匹配到备注: {possible_note}")
            for addr in addresses:
                note = addr.get('note', '')
                if note and (possible_note == note or possible_note in note or note in possible_note):
                    print(f"[DEBUG] 匹配到地址: {addr['address']}")
                    return addr['address']

    # 方法3：如果只有一个监控地址，直接返回
    if len(addresses) == 1:
        print(f"[DEBUG] 只有一个监控地址，直接返回: {addresses[0]['address']}")
        return addresses[0]['address']

    # 方法4：列出所有可用的备注名称
    notes = [a.get('note', '无备注') for a in addresses if a.get('note')]
    print(f"[DEBUG] 可用的备注名称: {notes}")

    print(f"[DEBUG] 未找到匹配的地址")
    return None

async def input_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理私聊的文本输入"""
    from datetime import datetime, timedelta
    import re
    
    chat = update.effective_chat
    print(f"[DEBUG] ========== input_router 开始 ==========")
    print(f"[DEBUG] 聊天类型: {chat.type}")
    print(f"[DEBUG] 消息内容: {update.message.text if update.message else 'None'}")

    if chat.type != 'private':
        print(f"[DEBUG] 不是私聊，跳过")
        return

    user_id = update.effective_user.id

    # ✅ 先定义 text 变量
    text = update.message.text.strip() if update.message.text else ""

    # 1. 检查群组管理状态
    from handlers.group_manager import user_states
    print(f"[DEBUG] 1. 检查群组管理状态: user_id in user_states = {user_id in user_states}")
    if user_id in user_states:
        print(f"[DEBUG] → 交给群组管理处理")
        from handlers.group_manager import handle_text_input
        await handle_text_input(update, context)
        return

    # 2. 检查广播模块状态
    in_broadcast = context.user_data.get("in_broadcast", False)
    print(f"[DEBUG] 2. 检查广播状态: in_broadcast = {in_broadcast}")
    if in_broadcast:
        print(f"[DEBUG] → 广播激活中，跳过（让 ConversationHandler 处理）")
        return

    # 3. 检查监控模块状态
    monitor_action = context.user_data.get("monitor_action")
    print(f"[DEBUG] 3. 检查监控状态: monitor_action = {monitor_action}")

    if monitor_action == "add":
        print(f"[DEBUG] → 交给监控模块添加地址")
        from handlers import monitor
        await monitor.monitor_add_input(update, context)
        return
    elif monitor_action == "add_note":
        print(f"[DEBUG] → 交给监控模块添加备注")
        from handlers import monitor
        await monitor.monitor_add_note(update, context)
        return

    # 4. 检查其他模块状态
    module = context.user_data.get("active_module")
    print(f"[DEBUG] 4. 检查其他模块: active_module = {module}")

    # 检查是否在互转查询的 ConversationHandler 状态中extract_address_from_text
    if context.user_data.get("transfer_results") is not None:
        print(f"[DEBUG] → 互转查询有结果数据，跳过 AI 回复")
        return

    if module == "transfer":
        print(f"[DEBUG] → 互转查询模块激活中，交给 ConversationHandler 处理")
        return
    if module == "operator":
        print(f"[DEBUG] → 交给操作员模块")
        await operator.handle_input(update, context)
        return
    elif module == "usdt":
        print(f"[DEBUG] → 交给 USDT 模块")
        try:
            await usdt.handle_input(update, context)
        except Exception as e:
            print(f"[DEBUG] USDT 模块错误: {e}")
            context.user_data.pop("active_module", None)
            context.user_data.pop("usdt_session", None)
            await update.message.reply_text("❌ USDT 查询出错，请重试")
        return
    elif module == "accounting":
        print(f"[DEBUG] → 记账模块，忽略")
        return

    # 检查是否是互转查询的地址格式
    transfer_pattern = r'^T[0-9A-Za-z]{33}\s+T[0-9A-Za-z]{33}$'
    if re.match(transfer_pattern, text):
        print(f"[DEBUG] 检测到互转查询地址格式，跳过 AI 回复，交给 ConversationHandler 处理")
        return

    # ========== 4.5 AI 数据分析对话 ==========
    print(f"[DEBUG] 4.5 检查私聊数据查询意图...")

    if text and not text.startswith('/'):
        # 权限检查
        from auth import is_authorized
        if not is_authorized(user_id):
            await update.message.reply_text(
                "❌ AI 对话功能仅限管理员和操作员使用\n\n"
                "如需使用，请联系 @ChinaEdward 申请权限"
            )
            return

        thinking_msg = await update.message.reply_text("🤔 思考中...")

        try:
            from handlers.ai_client import get_ai_client
            ai_client = get_ai_client()

            # 使用新的 chat_with_data 方法（AI 会自动获取数据并分析）
            reply = await ai_client.chat_with_data(text, user_id=user_id)

            if len(reply) > 4000:
                reply = reply[:4000] + "...\n\n(回复过长已截断)"

            await thinking_msg.edit_text(reply)
        except Exception as e:
            print(f"[DEBUG] AI 分析失败: {e}")
            await thinking_msg.edit_text(f"❌ AI 服务出错: {str(e)[:100]}")

        return

    # ========== 5. 其他情况（原有 AI 回复作为备用） ==========
    print(f"[DEBUG] 5. 检查 AI 回复权限...")
    print(f"[DEBUG] AI 回复文本: {text[:50] if text else '空'}")

    if not text or text.startswith('/'):
        print(f"[DEBUG] 文本为空或命令，跳过 AI")
        return

    # ✅ 权限检查：只有管理员和操作员才能使用 AI
    from auth import is_authorized
    if not is_authorized(user_id):
        print(f"[DEBUG] 用户 {user_id} 无权限使用 AI，跳过")
        await update.message.reply_text(
            "❌ AI 对话功能仅限管理员和操作员使用\n\n"
            "如需使用，请联系 @ChinaEdward 申请权限"
        )
        return

    thinking_msg = await update.message.reply_text("🤔 思考中...")
    print(f"[DEBUG] 已发送思考中消息")

    try:
        from handlers.ai_client import get_ai_client
        ai_client = get_ai_client()
        print(f"[DEBUG] AI 客户端获取成功")

        reply = await ai_client.chat(text)
        print(f"[DEBUG] AI 回复获取成功，长度: {len(reply)}")

        if len(reply) > 4000:
            reply = reply[:4000] + "...\n\n(回复过长已截断)"

        await thinking_msg.edit_text(reply)
        print(f"[DEBUG] AI 回复已发送")
    except Exception as e:
        print(f"[DEBUG] AI 调用失败: {e}")
        await thinking_msg.edit_text(f"❌ AI 服务出错: {str(e)[:100]}")

    print(f"[DEBUG] ========== input_router 结束 ==========")

# 自动保存群组信息（作为备份）
async def auto_save_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat and update.effective_chat.type in ['group', 'supergroup']:
        chat_id = str(update.effective_chat.id)
        title = update.effective_chat.title

        # 检查机器人是否还在群组中
        try:
            bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
            if bot_member.status not in ['member', 'administrator']:
                print(f"[DEBUG] 机器人不在群组 {title} ({chat_id}) 中，跳过保存")
                return
        except Exception as e:
            print(f"[DEBUG] 无法获取群组 {chat_id} 的成员状态: {e}")
            return

        print(f"[DEBUG] auto_save_group: 保存群组 {title} ({chat_id})")

        # 获取现有群组的分类（如果有）
        from db import get_all_groups_from_db
        existing_groups = get_all_groups_from_db()
        existing = next((g for g in existing_groups if g['id'] == chat_id), None)
        category = existing['category'] if existing else '未分类'

        # 保存时保留原有分类
        save_group(chat_id, title, category)
        # ✅ 新增：自动分类检测（仅当分类为"未分类"时）
        from db import update_group_category_if_needed

# main.py - 添加启动时自动分类函数

async def auto_classify_all_groups_on_startup(app: Application):
    """启动时对所有现有群组进行自动分类"""
    from db import get_all_groups_from_db, update_group_category_if_needed

    await asyncio.sleep(3)  # 等待机器人完全启动

    groups = get_all_groups_from_db()
    print(f"[自动分类] 开始检查 {len(groups)} 个群组的分类...")

    classified_count = 0
    for group in groups:
        group_id = group['id']
        group_name = group['title']
        current_category = group.get('category', '未分类')

        # 只处理未分类的群组
        if current_category == '未分类':
            if update_group_category_if_needed(group_id, group_name):
                classified_count += 1

    print(f"[自动分类] 完成！自动分类了 {classified_count} 个群组")

# 监听机器人加入/离开群组的事件
async def on_bot_join_or_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    专门处理机器人自己的成员状态变化。
    """
    my_chat_member = update.my_chat_member
    chat = my_chat_member.chat
    new_status = my_chat_member.new_chat_member.status
    old_status = my_chat_member.old_chat_member.status if my_chat_member.old_chat_member else None

    chat_id = str(chat.id)
    title = chat.title

    print(f"[DEBUG] 机器人状态变化 - 群组: {title} ({chat_id})")
    print(f"[DEBUG] 旧状态: {old_status}, 新状态: {new_status}")

    if new_status in ['member', 'administrator']:
        print(f"🎉 [系统事件] 机器人加入群组：{title} ({chat_id})")
        save_group(chat_id, title, '未分类')
        print(f"✅ [系统事件] 群组已自动存入数据库。")

    elif new_status in ['left', 'kicked', 'banned']:
        print(f"👋 [系统事件] 机器人离开/被踢出群组：{chat_id}")
        delete_group_from_db(chat_id)
        print(f"✅ [系统事件] 群组已从数据库删除。")

        # 等待一下，让 auto_save_group 不会重新保存
        await asyncio.sleep(1)

# main.py - 改进广播状态检测
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """全局取消命令 - 智能判断当前状态"""
    user_id = update.effective_user.id
    print(f"[DEBUG] cancel_command 被调用, user_id: {user_id}")

    # 🔥 先检查是否在群组管理状态
    from handlers.group_manager import user_states, handle_cancel_in_group_manager
    print(f"[DEBUG] user_states: {user_states}")

    if user_id in user_states:
        print(f"[DEBUG] 检测到群组管理状态，调用 handle_cancel_in_group_manager")
        await handle_cancel_in_group_manager(update, context)
        return

    # 🔥 广播状态 - 不需要在这里处理，因为 ConversationHandler 的 fallback 会处理
    # 直接返回，让广播自己的 fallback 处理
    if context.user_data.get("in_broadcast", False):
        print(f"[DEBUG] 检测到广播状态，跳过处理（让广播的 ConversationHandler 处理）")
        return

    # 清理其他模块的状态
    context.user_data.clear()
    print(f"[DEBUG] 清理其他模块状态")

    await update.message.reply_text("❌ 已取消所有操作")

    # 返回主菜单
    from handlers.menu import get_main_menu
    await update.message.reply_text(
        "请选择功能：",
        reply_markup=get_main_menu()
    )

# ========== 群组验证函数 ==========
async def verify_groups_on_startup(app: Application):
    """启动时验证所有群组，删除机器人不在的群组（增强版）"""
    from db import get_all_groups_from_db

    await asyncio.sleep(5)  # 等待机器人完全启动

    all_groups = get_all_groups_from_db()
    print(f"[启动检查] 开始验证 {len(all_groups)} 个群组...")

    groups_to_delete = []

    for group in all_groups:
        group_id = group['id']
        group_name = group.get('name', '未知群组')

        # 使用多种方法验证
        should_delete = False
        reason = ""

        # 方法1：尝试发送测试动作
        try:
            await app.bot.send_chat_action(chat_id=group_id, action="typing")
            print(f"[启动检查] 群组 {group_name} 可以发送动作，有效")
            continue  # 可以发送动作，说明机器人在群组中
        except Exception as e:
            error_msg = str(e).lower()
            if "chat not found" in error_msg:
                reason = "群组不存在"
                should_delete = True
            elif "bot was kicked" in error_msg:
                reason = "机器人被踢出"
                should_delete = True
            elif "bot is not a member" in error_msg:
                reason = "机器人不是成员"
                should_delete = True
            elif "group chat was upgraded" in error_msg:
                reason = "群组已升级"
                should_delete = True
            else:
                # 其他错误，尝试方法2
                print(f"[启动检查] 发送动作失败: {e}，尝试获取成员信息")

                # 方法2：获取成员信息
                try:
                    bot_member = await app.bot.get_chat_member(group_id, app.bot.id)
                    if bot_member.status not in ['member', 'administrator']:
                        reason = f"状态为 {bot_member.status}"
                        should_delete = True
                    else:
                        # 状态正常，可能是网络问题
                        print(f"[启动检查] 成员状态正常: {bot_member.status}")
                except Exception as e2:
                    error_msg2 = str(e2).lower()
                    if "chat not found" in error_msg2:
                        reason = "群组不存在"
                        should_delete = True
                    elif "bot was kicked" in error_msg2:
                        reason = "机器人被踢出"
                        should_delete = True
                    else:
                        reason = f"无法访问: {e2}"
                        should_delete = True

        if should_delete:
            print(f"[启动检查] 标记删除群组 {group_name} ({group_id}): {reason}")
            groups_to_delete.append(group_id)
        else:
            print(f"[启动检查] 群组 {group_name} 验证通过")

    # 删除无效的群组
    for group_id in groups_to_delete:
        print(f"[启动检查] 删除无效群组: {group_id}")
        delete_group_from_db(group_id)

    print(f"[启动检查] 完成！删除了 {len(groups_to_delete)} 个无效群组")

# main.py - 修改 periodic_group_verification 函数

async def periodic_group_verification(app: Application):
    """定期验证所有群组（每天执行一次）"""
    from db import get_all_groups_from_db

    all_groups = get_all_groups_from_db()
    print(f"[定期检查] 开始验证 {len(all_groups)} 个群组...")

    groups_to_delete = []

    for group in all_groups:
        group_id = group['id']
        group_name = group.get('name', '未知群组')

        try:
            # 尝试发送一个动作来测试连接
            await app.bot.send_chat_action(chat_id=group_id, action="typing")
            print(f"[定期检查] 群组 {group_name} 有效")
        except Exception as e:
            error_msg = str(e)
            # 如果是这些错误，说明机器人不在群组中
            if "chat not found" in error_msg.lower() or "bot was kicked" in error_msg.lower() or "bot is not a member" in error_msg.lower():
                print(f"[定期检查] 机器人不在群组 {group_name} ({group_id}) 中: {error_msg}")
                groups_to_delete.append(group_id)
            else:
                # 其他错误，可能是临时问题
                print(f"[定期检查] 群组 {group_name} 可能有问题: {error_msg}")
                # 尝试通过 get_chat 验证
                try:
                    await app.bot.get_chat(group_id)
                except:
                    groups_to_delete.append(group_id)

    # 删除无效的群组
    for group_id in groups_to_delete:
        print(f"[定期检查] 删除无效群组: {group_id}")
        delete_group_from_db(group_id)

    print(f"[定期检查] 完成！删除了 {len(groups_to_delete)} 个无效群组")

def main():
    # 初始化数据库和操作员
    init_db()
    from db import fix_joined_at
    fix_joined_at()
    init_operators_from_db()

    # 导入记账模块并初始化
    from handlers.accounting import init_accounting, get_conversation_handler, handle_group_message
    init_accounting(DB_PATH)

    # 创建应用
    app = Application.builder().token(BOT_TOKEN).build()

    async def cleanup_expired_states_job(context: ContextTypes.DEFAULT_TYPE):
        """定时清理过期状态"""
        from handlers.group_manager import cleanup_expired_states
        await cleanup_expired_states()

    # 定义手动清理命令（放在 main 函数内部）
    async def force_clean_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """手动强制清理所有机器人不在的群组"""
        user_id = update.effective_user.id
        if not is_authorized(user_id):
            await update.message.reply_text("❌ 只有管理员可以使用此命令")
            return

        msg = await update.message.reply_text("🔍 开始强制检查所有群组...")

        from db import get_all_groups_from_db
        groups = get_all_groups_from_db()
        deleted = 0
        kept = 0
        errors = 0

        for group in groups:
            group_id = group['id']
            group_name = group.get('name', '未知')

            try:
                # 尝试发送动作
                await context.bot.send_chat_action(chat_id=group_id, action="typing")
                kept += 1
                await msg.edit_text(f"✅ 仍在群组: {group_name}\n已检查: {kept + deleted + errors}/{len(groups)}")
            except Exception as e:
                error_msg = str(e).lower()
                if any(keyword in error_msg for keyword in ["chat not found", "bot was kicked", "bot is not a member", "group chat was upgraded"]):
                    delete_group_from_db(group_id)
                    deleted += 1
                    await msg.edit_text(f"🗑️ 已删除: {group_name}\n原因: {error_msg[:50]}\n已检查: {kept + deleted + errors}/{len(groups)}")
                else:
                    errors += 1
                    await msg.edit_text(f"⚠️ 检查失败: {group_name}\n错误: {error_msg[:50]}\n已检查: {kept + deleted + errors}/{len(groups)}")
                await asyncio.sleep(0.5)  # 避免请求过快

        await msg.edit_text(f"✅ 强制清理完成！\n\n删除: {deleted} 个无效群组\n保留: {kept} 个有效群组\n错误: {errors} 个检查失败")

    # 🔥 0. 全局取消命令（最高优先级，放在最前面）
    app.add_handler(CommandHandler("cancel", cancel_command))

    # 🔥 添加 skip 命令处理器
    from handlers.group_manager import skip_command
    app.add_handler(CommandHandler("skip", skip_command))

    # 1. 启动命令
    app.add_handler(CommandHandler("start", start))

    # 添加手动清理命令（新增这一行）
    app.add_handler(CommandHandler("clean", force_clean_groups))

    # 2. 添加 Git 更新命令（管理员专用）
    for handler in get_git_handlers():
        app.add_handler(handler)

    # 3. Transfer 对话处理器
    transfer_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(transfer.start_transfer_query, pattern="^trans_direct$"),
            CallbackQueryHandler(transfer.start_transfer_analysis, pattern="^trans_analysis$"),
            CallbackQueryHandler(transfer.handle_transfer_pagination, pattern="^trans_page_|^copy_addr_"),
        ],
        states={
            transfer.TRANSFER_QUERY_WAIT_ADDR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, transfer.process_transfer_query)
            ],
            transfer.TRANSFER_ANALYSIS_WAIT_ADDR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, transfer.process_transfer_analysis)
            ],
        },
        fallbacks=[CommandHandler("cancel", transfer.cancel_transfer)],
        per_message=False, 
    )
    app.add_handler(transfer_conv_handler)

    # 4. Broadcast 对话处理器
    for handler in broadcast.get_handlers():
        app.add_handler(handler)

    # 5. USDT 分页按钮
    app.add_handler(CallbackQueryHandler(usdt.handle_buttons, pattern="^usdt_"))

    # 6. 通用按钮路由（放在最后，处理其他所有未被处理的消息）
    app.add_handler(CallbackQueryHandler(button_router))

    # 7. 调试处理器（降低优先级，避免干扰命令）
    async def debug_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """调试用的消息处理器，显示所有收到的消息"""
        if update.message and update.message.text:
            if update.message.text.startswith('/'):
                return
            chat = update.effective_chat
            print(f"[DEBUG] 收到消息 - 聊天类型: {chat.type}, 聊天ID: {chat.id}, 文本: {update.message.text[:50]}")
        return None

    app.add_handler(MessageHandler(filters.ALL, debug_message_handler), group=10)

    # 8. 群组消息处理器（处理记账指令和计算器）
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
        handle_group_message
    ), group=1)

    # 9. 私聊文本输入路由（用于USDT、操作员管理等模块）
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
        input_router
    ), group=1)

    # 10. 全局群组消息捕获（备份用，用于保存群组信息）
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & ~filters.COMMAND, 
        auto_save_group
    ), group=2)

    # 11. 注册机器人成员状态监听器
    app.add_handler(ChatMemberHandler(on_bot_join_or_leave, ChatMemberHandler.MY_CHAT_MEMBER))

    # 12. 注册群组成员加入/退出监听器（服务消息方式，处理普通成员加入/退出）
    app.add_handler(get_service_message_handler())

    # 添加监控模块
    app.add_handler(CallbackQueryHandler(monitor.monitor_menu, pattern="^monitor_menu$"))
    app.add_handler(CallbackQueryHandler(monitor.monitor_list, pattern="^monitor_list$"))
    app.add_handler(CallbackQueryHandler(monitor.monitor_remove_start, pattern="^monitor_remove$"))

    # 添加监控模块的对话处理器
    monitor_conv_handler = monitor.get_monitor_conversation_handler()
    app.add_handler(monitor_conv_handler)

    # 添加取消命令
    app.add_handler(CommandHandler("cancel_monitor", monitor.monitor_cancel))

    # 添加定时任务（每30秒检查一次）
    async def start_monitor_check():
        """启动监控定时任务"""
        job_queue = app.job_queue
        if job_queue:
            job_queue.run_repeating(monitor.check_address_transactions, interval=30, first=10)
            print("✅ USDT 地址监控已启动（每30秒检查一次）")

    # 在 app 启动后添加定时任务（在 app.run_polling() 之前）
    if app.job_queue:
        app.job_queue.run_repeating(monitor.check_address_transactions, interval=30, first=10)
        print("✅ USDT 地址监控已启动（每30秒检查一次）")

    # ========== 添加启动验证和定期检查 ==========

    # 统一的 post_init 函数
    async def post_init(app: Application):
        """启动后初始化"""
        # 1. 启动验证群组
        #await verify_groups_on_startup(app)

        # 2. 启动自动分类（新增）
        await auto_classify_all_groups_on_startup(app)

        # 3. 启动状态清理任务
        job_queue = app.job_queue
        if job_queue:
            job_queue.run_repeating(
                cleanup_expired_states_job,
                interval=300,
                first=60
            )
            print("✅ 状态清理任务已启动（每5分钟检查一次）")
        else:
            print("⚠️ JobQueue 未启用，无法启动状态清理任务")

    # 设置统一的 post_init
    app.post_init = post_init

    # 使用 JobQueue 进行定期检查（每24小时）
    try:
        job_queue = app.job_queue
        if job_queue:
            # 每24小时执行一次定期检查
            job_queue.run_repeating(
                lambda context: periodic_group_verification(app),
                interval=86400,  # 24小时 = 86400秒
                first=3600  # 启动后1小时第一次执行
            )
            print("✅ 定期群组验证任务已启动（每24小时检查一次）")
        else:
            print("⚠️ JobQueue 未启用，无法启动定期群组验证")
    except Exception as e:
        print(f"⚠️ 启动定期群组验证失败: {e}")

    print("=" * 50)
    print("🤖 机器人启动成功...")
    print("=" * 50)
    print("已加载模块：")
    print("  ✅ Operator - 操作员管理")
    print("  ✅ USDT - USDT地址查询")
    print("  ✅ Accounting - 群组记账功能")
    print("  ✅ Broadcast - 群发消息")
    print("  ✅ Transfer - 转账查询和分析")
    print("  ✅ Group Manager - 群组分类管理")
    print("=" * 50)
    print("📌 功能提示：")
    print("  • 机器人加入群组时会自动记录")
    print("  • 退出群组时会自动清理数据")
    print("  • 启动时会自动验证所有群组并清理无效记录")
    print("  • 每24小时自动验证一次群组状态")
    print("  • 记账功能仅在群组中可用，支持以下指令：")
    print("    - +金额：添加入款")
    print("    - -金额：修正入款")
    print("    - 下发金额u：添加出款")
    print("    - 下发-金额u：修正出款")
    print("    - 设置手续费 数字：设置手续费率")
    print("    - 设置汇率 数字：设置汇率")
    print("    - 今日总：查看今日账单")
    print("    - 总：查看总计账单")
    print("    - 查询账单：按日期查询")
    print("    - 清理账单：清空所有记录")
    print("  • 计算器功能：群内发送如 100+200 即可计算")
    print("  • 群组管理：可创建分类，按分类筛选群组进行群发")
    print("=" * 50)

    # 启动机器人
    app.run_polling()

if __name__ == "__main__":
    main()
