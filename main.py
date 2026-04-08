# main.py - 修正后的版本

import asyncio
from handlers import monitor, operator
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
from handlers import operator, usdt, accounting, broadcast, transfer
from handlers.git_update import get_git_handlers
# 合并重复的导入
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

# 在 button_router 函数之前添加
async def extract_address_from_text(text: str) -> str:
    """从用户消息中提取地址（支持备注名称）"""
    import re
    from db import get_monitored_addresses

    # 先尝试匹配 TRC20 地址格式
    trc20_pattern = r'T[0-9A-Za-z]{33}'
    match = re.search(trc20_pattern, text)
    if match:
        return match.group()

    # 如果没有地址，尝试根据备注查找
    addresses = get_monitored_addresses()

    # 提取可能的备注关键词
    # 常见模式："地址xxx"、"备注xxx"、"爱德华"
    for keyword in ["地址", "备注", "分析"]:
        text = text.replace(keyword, "")

    # 清理文本，提取可能的备注名
    possible_note = text.strip()
    if possible_note:
        for addr in addresses:
            note = addr.get('note', '')
            if possible_note.lower() in note.lower() or note.lower() in possible_note.lower():
                return addr['address']

    # 如果都没找到，提示用户
    return None

async def input_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理私聊的文本输入"""
    from datetime import datetime, timedelta
    chat = update.effective_chat
    print(f"[DEBUG] ========== input_router 开始 ==========")
    print(f"[DEBUG] 聊天类型: {chat.type}")
    print(f"[DEBUG] 消息内容: {update.message.text if update.message else 'None'}")

    if chat.type != 'private':
        print(f"[DEBUG] 不是私聊，跳过")
        return

    user_id = update.effective_user.id

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

    # 检查是否在互转查询的 ConversationHandler 状态中
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

    # ========== 4.5 私聊中的意图识别和数据查询 ==========
    print(f"[DEBUG] 4.5 检查私聊数据查询意图...")
    text = update.message.text.strip() if update.message.text else ""

    if text and not text.startswith('/'):
        # 权限检查
        from auth import is_authorized
        if not is_authorized(user_id):
            await update.message.reply_text(
                "❌ AI 对话功能仅限管理员和操作员使用\n\n"
                "如需使用，请联系 @ChinaEdward 申请权限"
            )
            return

        # ========== 先直接匹配关键词（临时方案） ==========
        if "新加入" in text or "今天加入" in text:
            from db import get_all_groups_from_db
            from datetime import datetime, timezone, timedelta

            # 使用北京时间
            beijing_tz = timezone(timedelta(hours=8))
            now_beijing = datetime.now(beijing_tz)
            today_start_beijing = now_beijing.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

            groups = get_all_groups_from_db()
            today_joined = [g for g in groups if g.get('joined_at', 0) >= today_start_beijing]

            if today_joined:
                result = f"🆕 今天新加入了 {len(today_joined)} 个群组：\n"
                for g in today_joined:
                    joined_time = datetime.fromtimestamp(g.get('joined_at', 0), tz=beijing_tz).strftime('%H:%M')
                    result += f"• {g['title']}（{joined_time}）\n"
                await update.message.reply_text(result)
            else:
                await update.message.reply_text("📭 今天没有新加入的群组")
            return

        if "收入情况" in text or "交易情况" in text:
            from handlers.accounting import accounting_manager
            from db import get_all_groups_from_db
            groups = get_all_groups_from_db()
            group_details = []
            for group in groups:
                try:
                    stats = accounting_manager.get_today_stats(group['id'])
                    if stats['income_count'] > 0 or stats['expense_count'] > 0:
                        group_details.append({
                            'name': group['title'],
                            'income_usdt': stats['income_usdt'],
                            'expense_usdt': stats['expense_usdt']
                        })
                except:
                    pass
            if group_details:
                result = f"📊 今日有交易的群组：\n\n"
                for g in group_details:
                    result += f"• {g['name']}\n"
                    result += f"  入款：{g['income_usdt']:.0f} USDT"
                    if g['expense_usdt'] > 0:
                        result += f"，出款：{g['expense_usdt']:.0f} USDT"
                    result += "\n\n"
                await update.message.reply_text(result)
            else:
                await update.message.reply_text("📭 今日没有任何群组有交易记录")
            return

        # 使用 AI 识别意图
        from handlers.ai_client import get_ai_client
        ai_client = get_ai_client()

        intent_prompt = f"""判断用户问题的意图，只返回以下类型之一：

# 能力查询（新增）
- CAPABILITY_QUERY: 询问机器人能做什么、能分析哪些数据、有什么功能

# 基础统计
- TOTAL_GROUP_COUNT: 询问机器人总共加入了多少个群组
- GROUP_CATEGORY: 询问群组有哪些国家/分类
- TODAY_JOINED_GROUPS: 询问今天新加入的群组

# 收入统计
- TODAY_ALL_INCOME: 询问所有群组今天的收入/入款情况
- MONTH_TOTAL_INCOME: 询问本月所有群组的总收入
- PERIOD_COMPARISON: 询问本周vs上周、本月vs上月对比
- CATEGORY_INCOME_PERCENTAGE: 询问各分类入款占比
- GROUP_BILL: 查询指定群组的账单详情（如"查询XX群的账单"）

# 群组活跃度
- TODAY_ACTIVE_GROUPS: 询问今天哪些群组使用了记账功能
- TODAY_TOP_GROUP: 询问今天哪个群组交易最多
- GROUP_ACTIVITY_RANKING: 询问群组活跃度排行

# 用户统计
- TODAY_ACTIVE_USERS: 询问今天有谁使用了记账命令
- TODAY_TOP_USER: 询问今日入款最多的用户

# 待处理
- PENDING_USDT_GROUPS: 询问哪些群组有未下发的USDT

# 异常检测
- LARGE_TRANSACTION_ALERT: 询问大额交易提醒
- TODAY_HOURLY_DISTRIBUTION: 询问今日各时段入款分布

# 监听地址分析（新增）
- ADDRESS_INCOME_TODAY: 分析监听地址今天的收支情况
- ADDRESS_INCOME_WEEK: 分析监听地址本周的收支情况
- ADDRESS_INCOME_MONTH: 分析监听地址这个月的收支情况

# 其他
- OTHER: 其他问题

用户问题：{text}

只返回类型，不要其他内容。"""

        try:
            intent = await ai_client.chat(intent_prompt, "你是一个意图识别助手，只返回指定的类型代码。")
            intent = intent.strip().upper()
            print(f"[DEBUG] 意图识别结果: {intent}")
        except Exception as e:
            print(f"[DEBUG] 意图识别失败: {e}")
            intent = "OTHER"

        # ========== 0. 能力查询（机器人能做什么） ==========
        if intent == "CAPABILITY_QUERY":
            result = f"""📊 我可以帮你分析以下数据：

📁 **群组统计**
• 总共加入了多少个群组
• 群组有哪些国家/分类
• 今天新加入的群组

💰 **收入统计**
• 所有群组今天的收入情况（入款/出款/净收入）
• 本月所有群组的总收入
• 本周 vs 上周收入对比
• 各分类入款占比
• 指定群组的今日账单详情

📈 **群组活跃度**
• 今天哪些群组使用了记账功能
• 今天哪个群组交易最多
• 群组活跃度排行（按交易笔数）

👥 **用户统计**
• 今天谁使用了记账命令
• 今日入款最多的用户

⏳ **待处理**
• 哪些群组有未下发的USDT

⚠️ **异常检测**
• 大额交易提醒（≥5000元）
• 今日各时段入款分布

🔔 **监听地址分析**
• 监听地址今日收支情况
• 监听地址本周收支情况
• 监听地址本月收支情况

💡 直接提问即可，例如：
• "今天收入情况"
• "查询测试5群账单"
• "分析爱德华今天的收支"
• "哪些群组有未下发"
• "今日入款冠军是谁"
• "本周vs上周收入对比"

需要我帮你分析什么？"""
            await update.message.reply_text(result)
            return

        # ========== 1. 总群组数量 ==========
        if intent == "TOTAL_GROUP_COUNT":
            from db import get_all_groups_from_db
            groups = get_all_groups_from_db()
            count = len(groups)
            await update.message.reply_text(f"📊 当前机器人共加入 {count} 个群组")
            return

        # ========== 2. 群组分类 ==========
        elif intent == "GROUP_CATEGORY":
            from db import get_groups_by_category
            groups_by_cat = get_groups_by_category()
            if groups_by_cat:
                result = "📁 群组分类统计：\n"
                for cat, count in groups_by_cat.items():
                    if cat != '未分类':
                        result += f"• {cat}：{count} 个\n"
                if '未分类' in groups_by_cat:
                    result += f"• 未分类：{groups_by_cat['未分类']} 个\n"
                await update.message.reply_text(result)
            else:
                await update.message.reply_text("📭 暂无分类群组")
            return

        # ========== 3. 今天加入的群组 ==========
        elif intent == "TODAY_JOINED_GROUPS":
            from db import get_all_groups_from_db
            from datetime import datetime, timezone, timedelta

            # 使用北京时间
            beijing_tz = timezone(timedelta(hours=8))
            now_beijing = datetime.now(beijing_tz)
            today_start_beijing = now_beijing.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

            groups = get_all_groups_from_db()
            # 使用 joined_at 字段判断（joined_at 已经是北京时间戳）
            today_joined = [g for g in groups if g.get('joined_at', 0) >= today_start_beijing]

            if today_joined:
                # 按加入时间排序
                today_joined.sort(key=lambda x: x.get('joined_at', 0))

                result = f"🆕 今天新加入了 {len(today_joined)} 个群组：\n\n"
                for i, g in enumerate(today_joined, 1):
                    # 使用北京时间显示
                    joined_time = datetime.fromtimestamp(g.get('joined_at', 0), tz=beijing_tz).strftime('%H:%M')
                    result += f"{i}. {g['title']}\n"
                    result += f"   加入时间：{joined_time}\n"
                    result += f"   分类：{g.get('category', '未分类')}\n\n"
                await update.message.reply_text(result)
            else:
                await update.message.reply_text("📭 今天没有新加入的群组")
            return
        # ========== 4. 所有群组今日收入统计（分群显示） ==========
        elif intent == "TODAY_ALL_INCOME":
            from handlers.accounting import accounting_manager
            from db import get_all_groups_from_db
            from datetime import datetime

            groups = get_all_groups_from_db()

            # 收集每个有交易的群组数据
            group_details = []
            total_income_usdt = 0
            total_expense_usdt = 0

            for group in groups:
                try:
                    stats = accounting_manager.get_today_stats(group['id'])
                    # 只显示有交易的群组
                    if stats['income_count'] > 0 or stats['expense_count'] > 0:
                        group_details.append({
                            'name': group['title'],
                            'category': group.get('category', '未分类'),
                            'income_cny': stats['income_total'],
                            'income_usdt': stats['income_usdt'],
                            'income_count': stats['income_count'],
                            'expense_usdt': stats['expense_usdt'],
                            'expense_count': stats['expense_count'],
                            'pending': stats['pending_usdt']
                        })
                        total_income_usdt += stats['income_usdt']
                        total_expense_usdt += stats['expense_usdt']
                except:
                    pass

            if group_details:
                # 按入款金额排序
                group_details.sort(key=lambda x: x['income_usdt'], reverse=True)

                result = f"📊 今日有交易的群组（{len(group_details)}个）：\n\n"
                for g in group_details:
                    result += f"📌 {g['name']}（{g['category']}）\n"
                    result += f"   💰 入款：{g['income_cny']:.0f}元 = {g['income_usdt']:.0f} USDT（{g['income_count']}笔）\n"
                    if g['expense_usdt'] > 0:
                        result += f"   📤 出款：{g['expense_usdt']:.0f} USDT（{g['expense_count']}笔）\n"
                    if g['pending'] > 0:
                        result += f"   ⏳ 待下发：{g['pending']:.0f} USDT\n"
                    result += "\n"

                result += f"📊 今日汇总：\n"
                result += f"• 总入款：{total_income_usdt:.0f} USDT\n"
                result += f"• 总出款：{total_expense_usdt:.0f} USDT\n"
                result += f"• 净收入：{total_income_usdt - total_expense_usdt:.0f} USDT"

                await update.message.reply_text(result)
            else:
                await update.message.reply_text("📭 今日没有任何群组有交易记录")
            return
        # ========== 5. 今天哪些群组使用了记账功能 ==========
        elif intent == "TODAY_ACTIVE_GROUPS":
            from handlers.accounting import accounting_manager
            from db import get_all_groups_from_db
            groups = get_all_groups_from_db()
            active_groups = []

            for group in groups:
                try:
                    stats = accounting_manager.get_today_stats(group['id'])
                    if stats['income_count'] > 0 or stats['expense_count'] > 0:
                        active_groups.append({
                            'name': group['title'],
                            'income_count': stats['income_count'],
                            'expense_count': stats['expense_count'],
                            'income_usdt': stats['income_usdt']
                        })
                except:
                    pass

            if active_groups:
                result = f"📊 今日使用记账功能的群组（{len(active_groups)}个）：\n"
                for g in active_groups[:10]:
                    result += f"• {g['name']}：入款{g['income_count']}笔，{g['income_usdt']:.0f}U\n"
                await update.message.reply_text(result)
            else:
                await update.message.reply_text("📭 今日没有任何群组使用记账功能")
            return

        # ========== 6. 今天哪个群组交易最多 ==========
        elif intent == "TODAY_TOP_GROUP":
            from handlers.accounting import accounting_manager
            from db import get_all_groups_from_db
            groups = get_all_groups_from_db()
            top_group = None
            max_income = 0

            for group in groups:
                try:
                    stats = accounting_manager.get_today_stats(group['id'])
                    if stats['income_usdt'] > max_income:
                        max_income = stats['income_usdt']
                        top_group = group
                except:
                    pass

            if top_group:
                stats = accounting_manager.get_today_stats(top_group['id'])
                result = f"🏆 今日交易最多的群组：\n"
                result += f"• 群组：{top_group['title']}\n"
                result += f"• 入款：{stats['income_total']:.0f}元 = {stats['income_usdt']:.0f} USDT\n"
                result += f"• 笔数：{stats['income_count']}笔\n"
                await update.message.reply_text(result)
            else:
                await update.message.reply_text("📭 今日没有任何群组有交易记录")
            return

        # ========== 7. 哪些群组有未下发USDT ==========
        elif intent == "PENDING_USDT_GROUPS":
            from handlers.accounting import accounting_manager
            from db import get_all_groups_from_db
            groups = get_all_groups_from_db()
            pending_groups = []
            total_pending = 0

            for group in groups:
                try:
                    stats = accounting_manager.get_current_stats(group['id'])
                    if stats['pending_usdt'] > 0:
                        pending_groups.append({
                            'name': group['title'],
                            'pending': stats['pending_usdt']
                        })
                        total_pending += stats['pending_usdt']
                except:
                    pass

            if pending_groups:
                result = f"⏳ 有待下发的群组（{len(pending_groups)}个）：\n"
                for g in pending_groups[:10]:
                    result += f"• {g['name']}：{g['pending']:.0f} USDT\n"
                result += f"\n📊 总计待下发：{total_pending:.0f} USDT"
                await update.message.reply_text(result)
            else:
                await update.message.reply_text("✅ 所有群组均无待下发USDT")
            return

        # ========== 8. 今天谁使用了记账命令 ==========
        elif intent == "TODAY_ACTIVE_USERS":
            from handlers.accounting import accounting_manager
            from db import get_all_groups_from_db
            from collections import defaultdict

            groups = get_all_groups_from_db()
            user_activity = defaultdict(lambda: {'count': 0, 'groups': set(), 'income': 0})

            for group in groups:
                try:
                    records = accounting_manager.get_today_records(group['id'])
                    for record in records:
                        user_id_key = record.get('user_id')
                        display_name = record.get('display_name', str(user_id_key))
                        user_activity[user_id_key]['name'] = display_name
                        user_activity[user_id_key]['count'] += 1
                        user_activity[user_id_key]['groups'].add(group['title'])
                        if record['type'] == 'income':
                            user_activity[user_id_key]['income'] += record['amount']
                except:
                    pass

            if user_activity:
                sorted_users = sorted(user_activity.items(), key=lambda x: x[1]['count'], reverse=True)
                result = f"👥 今日使用记账命令的用户（{len(sorted_users)}人）：\n"
                for uid, data in sorted_users[:10]:
                    result += f"• {data['name']}：{data['count']}次，入款{data['income']:.0f}元\n"
                await update.message.reply_text(result)
            else:
                await update.message.reply_text("📭 今日无人使用记账命令")
            return

        # ========== 9. 本月所有群组总收入 ==========
        elif intent == "MONTH_TOTAL_INCOME":
            from handlers.accounting import accounting_manager
            from db import get_all_groups_from_db
            from datetime import datetime, timezone, timedelta

            # 使用北京时间
            beijing_tz = timezone(timedelta(hours=8))
            now_beijing = datetime.now(beijing_tz)
            month_start_beijing = now_beijing.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()

            groups = get_all_groups_from_db()
            total_income_cny = 0
            total_income_usdt = 0

            for group in groups:
                try:
                    records = accounting_manager.get_total_records(group['id'])
                    for record in records:
                        if record['type'] == 'income' and record.get('created_at', 0) >= month_start_beijing:
                            total_income_cny += record['amount']
                            total_income_usdt += record['amount_usdt']
                except:
                    pass

            current_month = now_beijing.strftime('%Y年%m月')
            result = f"📊 {current_month}所有群组总收入：\n"
            result += f"• 总入款：{total_income_cny:.2f} 元 = {total_income_usdt:.2f} USDT"
            await update.message.reply_text(result)
            return

        # ========== 10. 群组活跃度排行 ==========
        elif intent == "GROUP_ACTIVITY_RANKING":
            from handlers.accounting import accounting_manager
            from db import get_all_groups_from_db
            groups = get_all_groups_from_db()
            group_stats = []

            for group in groups:
                try:
                    stats = accounting_manager.get_total_stats(group['id'])
                    if stats['income_count'] > 0 or stats['expense_count'] > 0:
                        group_stats.append({
                            'name': group['title'],
                            'total_income': stats['income_usdt'],
                            'total_count': stats['income_count'] + stats['expense_count']
                        })
                except:
                    pass

            group_stats.sort(key=lambda x: x['total_count'], reverse=True)

            if group_stats:
                result = "🏆 群组活跃度排行（按交易笔数）：\n"
                for i, g in enumerate(group_stats[:5], 1):
                    result += f"{i}. {g['name']}：{g['total_count']}笔，{g['total_income']:.0f}U\n"
                await update.message.reply_text(result)
            else:
                await update.message.reply_text("📭 暂无群组活跃数据")
            return

        # ========== 11. 今日入款最多的用户 ==========
        elif intent == "TODAY_TOP_USER":
            from handlers.accounting import accounting_manager
            from db import get_all_groups_from_db
            from collections import defaultdict

            groups = get_all_groups_from_db()
            user_income = defaultdict(float)
            user_name_map = {}

            for group in groups:
                try:
                    records = accounting_manager.get_today_records(group['id'])
                    for record in records:
                        if record['type'] == 'income':
                            user_id_key = record.get('user_id')
                            user_name_map[user_id_key] = record.get('display_name', str(user_id_key))
                            user_income[user_id_key] += record['amount']
                except:
                    pass

            if user_income:
                top_user = max(user_income.items(), key=lambda x: x[1])
                result = f"🏆 今日入款冠军：\n"
                result += f"• 用户：{user_name_map.get(top_user[0], top_user[0])}\n"
                result += f"• 入款：{top_user[1]:.2f} 元"
                await update.message.reply_text(result)
            else:
                await update.message.reply_text("📭 今日暂无入款记录")
            return

        # ========== 12. 本周vs上周对比 ==========
        elif intent == "PERIOD_COMPARISON":
            from handlers.accounting import accounting_manager
            from db import get_all_groups_from_db
            from datetime import datetime, timezone, timedelta

            # 使用北京时间
            beijing_tz = timezone(timedelta(hours=8))
            now_beijing = datetime.now(beijing_tz)

            # 本周一（北京时间）
            this_week_start = (now_beijing - timedelta(days=now_beijing.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            # 上周一
            last_week_start = this_week_start - timedelta(days=7)
            # 上周日结束
            last_week_end = this_week_start - timedelta(seconds=1)

            this_week_total = 0
            last_week_total = 0

            # ✅ 获取群组列表
            groups = get_all_groups_from_db()

            for group in groups:
                try:
                    records = accounting_manager.get_total_records(group['id'])
                    for record in records:
                        if record['type'] == 'income':
                            ts = record.get('created_at', 0)
                            if this_week_start.timestamp() <= ts:
                                this_week_total += record['amount_usdt']
                            elif last_week_start.timestamp() <= ts < last_week_end.timestamp():
                                last_week_total += record['amount_usdt']
                except:
                    pass

            if this_week_total > 0 or last_week_total > 0:
                change = ((this_week_total - last_week_total) / last_week_total * 100) if last_week_total > 0 else 100
                trend = "📈 上涨" if change >= 0 else "📉 下跌"
                result = f"📊 本周 vs 上周对比：\n"
                result += f"• 本周收入：{this_week_total:.0f} USDT\n"
                result += f"• 上周收入：{last_week_total:.0f} USDT\n"
                result += f"• {trend} {abs(change):.1f}%"
                await update.message.reply_text(result)
            else:
                await update.message.reply_text("📭 暂无周度数据对比")
            return
        # ========== 13. 各分类入款占比 ==========
        elif intent == "CATEGORY_INCOME_PERCENTAGE":
            from handlers.accounting import accounting_manager
            from db import get_all_groups_from_db

            groups = get_all_groups_from_db()
            category_income = {}
            total = 0

            for group in groups:
                try:
                    records = accounting_manager.get_total_records(group['id'])
                    for record in records:
                        if record['type'] == 'income':
                            category = record.get('category', '未分类')
                            if not category:
                                category = '未分类'
                            category_income[category] = category_income.get(category, 0) + record['amount_usdt']
                            total += record['amount_usdt']
                except:
                    pass

            if total > 0:
                sorted_cats = sorted(category_income.items(), key=lambda x: x[1], reverse=True)
                result = f"📊 各分类入款占比：\n"
                for cat, amount in sorted_cats[:5]:
                    percentage = amount / total * 100
                    result += f"• {cat}：{amount:.0f} USDT（{percentage:.1f}%）\n"
                await update.message.reply_text(result)
            else:
                await update.message.reply_text("📭 暂无入款数据")
            return
        # ========== 14. 今日各时段入款分布 ==========
        elif intent == "TODAY_HOURLY_DISTRIBUTION":
            from handlers.accounting import accounting_manager
            from db import get_all_groups_from_db
            from datetime import datetime, timezone, timedelta

            # 使用北京时间时区
            beijing_tz = timezone(timedelta(hours=8))

            groups = get_all_groups_from_db()
            hourly_data = [0] * 24

            for group in groups:
                try:
                    records = accounting_manager.get_today_records(group['id'])
                    for record in records:
                        if record['type'] == 'income':
                            hour = datetime.fromtimestamp(record['created_at'], tz=beijing_tz).hour
                            hourly_data[hour] += record['amount_usdt']
                except:
                    pass

            peak_hour = max(range(24), key=lambda x: hourly_data[x])
            active_hours = [(h, hourly_data[h]) for h in range(24) if hourly_data[h] > 0]

            if active_hours:
                result = f"⏰ 今日入款时段分布：\n"
                result += f"• 高峰时段：{peak_hour}:00-{peak_hour+1}:00，{hourly_data[peak_hour]:.0f} USDT\n"
                result += f"• 活跃时段：{', '.join([f'{h}:00' for h, _ in active_hours[:5]])}"
                await update.message.reply_text(result)
            else:
                await update.message.reply_text("📭 今日暂无入款记录")
            return

        # ========== 15. 大额交易提醒 ==========
        elif intent == "LARGE_TRANSACTION_ALERT":
            from handlers.accounting import accounting_manager
            from db import get_all_groups_from_db
            from datetime import datetime, timezone, timedelta

            # 使用北京时间时区
            beijing_tz = timezone(timedelta(hours=8))

            groups = get_all_groups_from_db()
            large_threshold = 5000
            large_transactions = []

            for group in groups:
                try:
                    records = accounting_manager.get_today_records(group['id'])
                    for record in records:
                        if record['type'] == 'income' and record['amount'] >= large_threshold:
                            # 使用北京时间格式化时间
                            time_str = datetime.fromtimestamp(record['created_at'], tz=beijing_tz).strftime('%H:%M')
                            large_transactions.append({
                                'group': group['title'],
                                'user': record.get('display_name', '未知'),
                                'amount': record['amount'],
                                'time': time_str
                            })
                except:
                    pass

            if large_transactions:
                result = f"⚠️ 今日大额入款提醒（≥{large_threshold}元）：\n"
                for tx in large_transactions[:5]:
                    result += f"• {tx['time']} {tx['group']} - {tx['user']}：{tx['amount']:.0f}元\n"
                await update.message.reply_text(result)
            else:
                await update.message.reply_text(f"✅ 今日无大额入款（≥{large_threshold}元）")
            return

        # ========== 16. 查询指定群组账单 ==========
        elif intent == "GROUP_BILL":
            from handlers.accounting import accounting_manager
            from db import get_all_groups_from_db
            from datetime import datetime, timezone, timedelta

            # 使用北京时间时区
            beijing_tz = timezone(timedelta(hours=8))

            # 提取群组名称
            import re
            group_name_match = re.search(r'[「"\'【]?(.+?)[」"\'】]?群', text)
            if not group_name_match:
                # 尝试其他匹配方式
                for word in ["查询", "查看", "的账单", "账单"]:
                    text = text.replace(word, "")
                group_name = text.strip()
            else:
                group_name = group_name_match.group(1)

            # 查找群组
            groups = get_all_groups_from_db()
            target_group = None
            for group in groups:
                if group_name.lower() in group['title'].lower():
                    target_group = group
                    break

            if not target_group:
                await update.message.reply_text(f"❌ 未找到群组「{group_name}」")
                return

            # 获取账单
            stats = accounting_manager.get_today_stats(target_group['id'])
            records = accounting_manager.get_today_records(target_group['id'])

            if stats['income_count'] == 0 and stats['expense_count'] == 0:
                await update.message.reply_text(f"📭 群组「{target_group['title']}」今日无记账记录")
                return

            result = f"📊 群组「{target_group['title']}」今日账单：\n\n"
            result += f"💰 入款：{stats['income_total']:.2f}元 = {stats['income_usdt']:.2f} USDT（{stats['income_count']}笔）\n"
            result += f"📤 出款：{stats['expense_usdt']:.2f} USDT（{stats['expense_count']}笔）\n"
            result += f"⏳ 待下发：{stats['pending_usdt']:.2f} USDT\n"

            # 显示最近的几笔记录
            if records:
                result += f"\n📋 最近记录：\n"
                for r in records[:5]:
                    time_str = datetime.fromtimestamp(r['created_at'], tz=beijing_tz).strftime('%H:%M')
                    if r['type'] == 'income':
                        result += f"  {time_str} +{r['amount']:.0f}元 = {r['amount_usdt']:.0f}U"
                    else:
                        result += f"  {time_str} 下发 {r['amount_usdt']:.0f}U"
                    if r.get('category'):
                        result += f" [{r['category']}]"
                    result += f" {r.get('display_name', '')}\n"

            await update.message.reply_text(result)
            return

        # ========== 17. 监听地址今日收支分析 ==========
        elif intent == "ADDRESS_INCOME_TODAY":
            from handlers.monitor import get_trc20_transactions, get_address_balance
            from db import get_monitored_addresses
            from datetime import datetime, timezone, timedelta

            # 使用北京时间
            beijing_tz = timezone(timedelta(hours=8))
            now_beijing = datetime.now(beijing_tz)
            today_start_beijing = int(now_beijing.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)

            # 提取地址或备注名称
            address = await extract_address_from_text(text)
            if not address:
                await update.message.reply_text("❌ 请提供要分析的监控地址或备注名称")
                return

            # 获取交易记录
            txs = await get_trc20_transactions(address, today_start_beijing)

            received = 0.0
            sent = 0.0
            for tx in txs:
                to_addr = tx.get("to", "")
                raw_amount = tx.get("value", 0)
                amount = int(raw_amount) / 1_000_000 if raw_amount else 0

                if to_addr == address:
                    received += amount
                else:
                    sent += amount

            # 获取当前余额
            balance = await get_address_balance(address)

            # 获取备注
            addresses = get_monitored_addresses()
            note = ""
            for a in addresses:
                if a['address'] == address:
                    note = a.get('note', '')
                    break

            short_addr = f"{address[:8]}...{address[-6:]}"
            addr_display = f"{short_addr} ({note})" if note else short_addr

            result = f"💰 监听地址 {addr_display} 今日收支：\n\n"
            result += f"• 收到：{received:.2f} USDT\n"
            result += f"• 转出：{sent:.2f} USDT\n"
            result += f"• 净收入：{received - sent:.2f} USDT\n"
            result += f"• 当前余额：{balance:.2f} USDT"

            await update.message.reply_text(result)
            return

        # ========== 18. 监听地址本周收支分析 ==========
        elif intent == "ADDRESS_INCOME_WEEK":
            from handlers.monitor import get_trc20_transactions, get_address_balance
            from db import get_monitored_addresses
            from datetime import datetime, timezone, timedelta

            # 使用北京时间
            beijing_tz = timezone(timedelta(hours=8))
            now_beijing = datetime.now(beijing_tz)
            # 本周一（北京时间）
            week_start_beijing = (now_beijing - timedelta(days=now_beijing.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            week_start_ts = int(week_start_beijing.timestamp() * 1000)

            # 提取地址或备注名称
            address = await extract_address_from_text(text)
            if not address:
                await update.message.reply_text("❌ 请提供要分析的监控地址或备注名称")
                return

            # 获取交易记录
            txs = await get_trc20_transactions(address, week_start_ts)

            received = 0.0
            sent = 0.0
            for tx in txs:
                to_addr = tx.get("to", "")
                raw_amount = tx.get("value", 0)
                amount = int(raw_amount) / 1_000_000 if raw_amount else 0

                if to_addr == address:
                    received += amount
                else:
                    sent += amount

            # 获取当前余额
            balance = await get_address_balance(address)

            # 获取备注
            addresses = get_monitored_addresses()
            note = ""
            for a in addresses:
                if a['address'] == address:
                    note = a.get('note', '')
                    break

            short_addr = f"{address[:8]}...{address[-6:]}"
            addr_display = f"{short_addr} ({note})" if note else short_addr

            result = f"💰 监听地址 {addr_display} 本周收支：\n\n"
            result += f"• 收到：{received:.2f} USDT\n"
            result += f"• 转出：{sent:.2f} USDT\n"
            result += f"• 净收入：{received - sent:.2f} USDT\n"
            result += f"• 当前余额：{balance:.2f} USDT"

            await update.message.reply_text(result)
            return

        # ========== 19. 监听地址本月收支分析 ==========
        elif intent == "ADDRESS_INCOME_MONTH":
            from handlers.monitor import get_trc20_transactions, get_address_balance
            from db import get_monitored_addresses
            from datetime import datetime, timezone, timedelta

            # 使用北京时间
            beijing_tz = timezone(timedelta(hours=8))
            now_beijing = datetime.now(beijing_tz)
            # 本月1日（北京时间）
            month_start_beijing = now_beijing.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            month_start_ts = int(month_start_beijing.timestamp() * 1000)

            # 提取地址或备注名称
            address = await extract_address_from_text(text)
            if not address:
                await update.message.reply_text("❌ 请提供要分析的监控地址或备注名称")
                return

            # 获取交易记录
            txs = await get_trc20_transactions(address, month_start_ts)

            received = 0.0
            sent = 0.0
            for tx in txs:
                to_addr = tx.get("to", "")
                raw_amount = tx.get("value", 0)
                amount = int(raw_amount) / 1_000_000 if raw_amount else 0

                if to_addr == address:
                    received += amount
                else:
                    sent += amount

            # 获取当前余额
            balance = await get_address_balance(address)

            # 获取备注
            addresses = get_monitored_addresses()
            note = ""
            for a in addresses:
                if a['address'] == address:
                    note = a.get('note', '')
                    break

            short_addr = f"{address[:8]}...{address[-6:]}"
            addr_display = f"{short_addr} ({note})" if note else short_addr

            result = f"💰 监听地址 {addr_display} 本月收支：\n\n"
            result += f"• 收到：{received:.2f} USDT\n"
            result += f"• 转出：{sent:.2f} USDT\n"
            result += f"• 净收入：{received - sent:.2f} USDT\n"
            result += f"• 当前余额：{balance:.2f} USDT"

            await update.message.reply_text(result)
            return

        # ========== 其他意图，继续 AI 对话 ==========
        else:
            print(f"[DEBUG] 意图为 OTHER，继续 AI 对话")

    # ========== 5. AI 回复（需要管理员或操作员权限） ==========
    print(f"[DEBUG] 5. 检查 AI 回复权限...")
    text = update.message.text.strip() if update.message.text else ""
    print(f"[DEBUG] AI 回复文本: {text[:50] if text else '空'}")

    if not text or text.startswith('/'):
        print(f"[DEBUG] 文本为空或命令，跳过 AI")
        return

    # 检查是否是互转查询的地址格式
    import re
    transfer_pattern = r'^T[0-9A-Za-z]{33}\s+T[0-9A-Za-z]{33}$'
    if re.match(transfer_pattern, text):
        print(f"[DEBUG] 检测到互转查询地址格式，跳过 AI 回复，交给 ConversationHandler 处理")
        return

    # ✅ 权限检查：只有管理员和操作员才能使用 AI
    from auth import is_authorized
    user_id = update.effective_user.id
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
        update_group_category_if_needed(chat_id, title)

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
        await verify_groups_on_startup(app)

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
