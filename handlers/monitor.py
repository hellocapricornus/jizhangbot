# handlers/monitor.py - 完整版（带备注功能）

import asyncio
import re
import time
from datetime import datetime, timedelta, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters, ConversationHandler, CommandHandler
from auth import is_authorized, OWNER_ID
from db import (
    get_monitored_addresses, add_monitored_address, remove_monitored_address,
    update_address_last_check, add_transaction_record, is_tx_notified, mark_tx_notified
)

# 状态定义
MONITOR_MENU = 0
MONITOR_ADD = 1
MONITOR_ADD_NOTE = 2
MONITOR_REMOVE = 3

# 设置北京时区
BEIJING_TZ = timezone(timedelta(hours=8))

# API 配置
TRONGRID_API = "https://api.trongrid.io"
TRONGRID_API_KEY = "b7f1c9fa-a622-49ad-972e-9ce838faccbe"  # 添加你的 API Key
USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

async def get_address_balance(address: str) -> float:
    """获取地址的 USDT 余额"""
    import aiohttp
    try:
        url = f"{TRONGRID_API}/v1/accounts/{address}"
        headers = {"TRON-PRO-API-KEY": TRONGRID_API_KEY}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:  # 添加 headers 参数
                data = await resp.json()
                if data.get('data') and len(data['data']) > 0:
                    trc20 = data['data'][0].get('trc20', [])
                    for token in trc20:
                        if USDT_CONTRACT in token:
                            return int(token[USDT_CONTRACT]) / 1_000_000
    except Exception as e:
        print(f"查询余额失败: {e}")
    return 0.0

async def get_monthly_stats(address: str) -> dict:
    """获取地址本月的 USDT 收支统计"""
    import aiohttp
    from datetime import datetime
    
    # 获取本月第一天的时间戳（北京时间）
    now = datetime.now()
    first_day = datetime(now.year, now.month, 1, 0, 0, 0)
    start_timestamp = int(first_day.timestamp())
    
    total_received = 0.0
    total_sent = 0.0
    
    try:
        url = f"{TRONGRID_API}/v1/accounts/{address}/transactions/trc20"
        headers = {"TRON-PRO-API-KEY": TRONGRID_API_KEY}  # 添加请求头
        params = {
            "contract_address": USDT_CONTRACT,
            "limit": 200,
            "min_timestamp": start_timestamp * 1000
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    txs = data.get("data", [])
                    
                    for tx in txs:
                        from_addr = tx.get("from", "")
                        to_addr = tx.get("to", "")
                        raw_amount = tx.get("value", 0)
                        amount = int(raw_amount) / 1_000_000 if raw_amount else 0
                        
                        if to_addr == address:
                            total_received += amount
                        elif from_addr == address:
                            total_sent += amount
    except Exception as e:
        print(f"查询月度统计失败: {e}")
    
    return {
        "received": total_received,
        "sent": total_sent,
        "net": total_received - total_sent
    }

async def get_trc20_transactions(address: str, min_timestamp: int = 0, limit: int = 200, offset: int = 0):
    """获取 TRC20 USDT 交易记录（支持分页）"""
    import aiohttp
    try:
        url = f"{TRONGRID_API}/v1/accounts/{address}/transactions/trc20"
        headers = {"TRON-PRO-API-KEY": TRONGRID_API_KEY}
        params = {
            "contract_address": USDT_CONTRACT,
            "limit": limit,
            "min_timestamp": min_timestamp if min_timestamp > 0 else 0,
            "offset": offset  # 新增 offset 参数
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("data", [])
    except Exception as e:
        print(f"查询交易失败: {e}")
    return []


async def check_address_transactions(context: ContextTypes.DEFAULT_TYPE):
    """定时检查监控地址的交易"""
    addresses = get_monitored_addresses()
    if not addresses:
        return

    current_time = int(time.time())
    bot = context.bot

    for addr_info in addresses:
        address = addr_info["address"]
        last_check = addr_info.get("last_check", 0)
        added_by = addr_info.get("added_by")
        note = addr_info.get("note", "")

        # 获取新交易（从上次检查时间之后）
        txs = await get_trc20_transactions(address, last_check)

        if txs:
            # 更新最后检查时间
            update_address_last_check(address, current_time)

            # 获取当前余额
            current_balance = await get_address_balance(address)

            monthly_stats = await get_monthly_stats(address)

            for tx in txs:
                tx_id = tx.get("transaction_id", "")
                from_addr = tx.get("from", "")
                to_addr = tx.get("to", "")
                raw_amount = tx.get("value", 0)
                amount = int(raw_amount) / 1_000_000 if raw_amount else 0
                timestamp = tx.get("block_timestamp", 0) / 1000

                # 检查是否已通知过
                if is_tx_notified(tx_id):
                    continue

                # 记录交易
                add_transaction_record(address, tx_id, from_addr, to_addr, amount, int(timestamp))

                # 发送通知
                direction = "收到" if to_addr == address else "转出"
                short_from = f"{from_addr[:6]}...{from_addr[-6:]}" if len(from_addr) > 12 else from_addr
                short_to = f"{to_addr[:6]}...{to_addr[-6:]}" if len(to_addr) > 12 else to_addr

                # 时间转换为北京时间
                utc_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                beijing_time = utc_time.astimezone(BEIJING_TZ)
                time_str = beijing_time.strftime('%Y-%m-%d %H:%M:%S')

                # 构建消息（包含备注）
                message = (
                    f"🔔 **USDT 交易监控提醒**\n\n"
                    f"📌 监控地址：`{address[:8]}...{address[-6:]}`\n"
                )

                # 如果有备注，显示备注
                if note:
                    message += f"📝 备注：{note}\n"
                else:
                    message += "\n"

                message += f"💎 当前余额：**{current_balance:.2f} USDT**\n\n"

                message += (
                    f"💰 金额：**{amount:.2f} USDT**\n"
                    f"🔄 方向：{direction}\n"
                    f"📤 发送方：`{short_from}`\n"
                    f"📥 接收方：`{short_to}`\n"
                    f"⏰ 时间：{time_str}\n\n"
                )

                message += (
                    f"📅 **本月统计**\n"
                    f"• 累计收到：**{monthly_stats['received']:.2f} USDT**\n"
                    f"• 累计转出：**{monthly_stats['sent']:.2f} USDT**\n"
                    f"• 净收入：**{monthly_stats['net']:.2f} USDT**\n\n"
                )

                # 只发送给添加该地址的用户
                try:
                    await bot.send_message(chat_id=added_by, text=message, parse_mode="Markdown")
                    print(f"✅ 已发送监控通知给用户 {added_by} (备注: {note or '无'})")
                except Exception as e:
                    print(f"发送给用户 {added_by} 失败: {e}")

                # 标记为已通知
                mark_tx_notified(tx_id)


async def monitor_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """USDT 地址监控菜单"""
    query = update.callback_query
    user_id = query.from_user.id

    if not is_authorized(user_id):
        await query.answer("❌ 无权限", show_alert=True)
        return

    await query.answer()

    addresses = get_monitored_addresses(user_id=user_id)

    keyboard = [
        [InlineKeyboardButton("➕ 添加监控地址", callback_data="monitor_add")],
        [InlineKeyboardButton("📋 查看监控列表", callback_data="monitor_list")],
        [InlineKeyboardButton("📊 月度统计", callback_data="monitor_stats")],
        [InlineKeyboardButton("❌ 删除监控地址", callback_data="monitor_remove")],
        [InlineKeyboardButton("◀️ 返回主菜单", callback_data="main_menu")]
    ]

    if len(addresses) == 0:
        text = (
            "🔔 USDT 地址监控\n\n"
            f"📊 您的监控地址数：0 个\n\n"
            "⚠️ 暂无监控地址，请先添加监控地址。\n\n"
            "当您监控的地址有 USDT 交易时，会发送通知给您。\n\n"
            "💡 提示：监控间隔约 30 秒\n\n"
            "📝 支持为地址添加备注，方便识别"
        )
    else:
        text = (
            "🔔 USDT 地址监控\n\n"
            f"📊 您的监控地址数：{len(addresses)} 个\n\n"
            "当您监控的地址有 USDT 交易时，会发送通知给您。\n\n"
            "💡 提示：监控间隔约 30 秒\n\n"
            "📝 支持为地址添加备注，方便识别"
        )

    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def monitor_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看监控地址的月度统计"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_authorized(user_id):
        await query.answer("❌ 无权限", show_alert=True)
        return
    
    await query.answer()
    
    addresses = get_monitored_addresses(user_id=user_id)
    
    if not addresses:
        await query.message.edit_text("📭 您还没有添加任何监控地址")
        await asyncio.sleep(1)
        await monitor_menu(update, context)
        return
    
    # 发送"查询中"提示
    await query.message.edit_text("📊 正在查询月度统计，请稍候...")
    
    text = "📊 **监控地址月度统计**\n\n"
    
    for addr_info in addresses:
        address = addr_info["address"]
        note = addr_info.get("note", "")
        short_addr = f"{address[:8]}...{address[-6:]}"
        
        stats = await get_monthly_stats(address)
        
        text += f"📌 {short_addr}"
        if note:
            text += f" ({note})"
        text += f"\n   💰 本月收到：**{stats['received']:.2f} USDT**"
        text += f"\n   📤 本月转出：**{stats['sent']:.2f} USDT**"
        text += f"\n   📈 净收入：**{stats['net']:.2f} USDT**\n\n"
    
    keyboard = [[InlineKeyboardButton("◀️ 返回", callback_data="monitor_menu")]]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def monitor_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始添加监控地址"""
    query = update.callback_query
    await query.answer()

    context.user_data["monitor_action"] = "add"

    text = (
        "➕ 添加监控地址\n\n"
        "请输入要监控的 USDT 地址：\n\n"
        "支持格式：\n"
        "• TRC20: T 开头，34位\n"
        "• ERC20: 0x 开头，42位\n\n"
        "❌ 输入 /cancel_monitor 取消"
    )

    try:
        await query.message.edit_text(text, parse_mode=None)
    except Exception as e:
        await query.message.reply_text(text, parse_mode=None)

    return MONITOR_ADD


async def monitor_add_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理添加地址输入"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text == "/cancel_monitor":
        context.user_data.pop("monitor_action", None)
        await update.message.reply_text("❌ 已取消添加")
        await monitor_menu_from_message(update, context)
        return ConversationHandler.END

    # 验证地址格式
    trc20_pattern = r'^T[0-9A-Za-z]{33}$'
    erc20_pattern = r'^0x[0-9a-fA-F]{40}$'

    if re.match(trc20_pattern, text):
        chain_type = "TRC20"
        address = text
    elif re.match(erc20_pattern, text):
        chain_type = "ERC20"
        address = text
    else:
        await update.message.reply_text("❌ 地址格式不正确，请重新输入：\n\n输入 /cancel_monitor 取消")
        return MONITOR_ADD

    # 保存地址信息，等待输入备注
    context.user_data["monitor_temp"] = {
        "address": address,
        "chain_type": chain_type
    }
    context.user_data["monitor_action"] = "add_note"

    await update.message.reply_text(
        f"✅ 地址已识别：`{address}` ({chain_type})\n\n"
        "📝 请输入备注（可选，用于标识这个地址）：\n"
        "例如：币安钱包、个人钱包、测试地址等\n\n"
        "直接发送 /skip 跳过备注\n\n"
        "❌ 输入 /cancel_monitor 取消",
        parse_mode=None
    )
    return MONITOR_ADD_NOTE


async def monitor_add_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理备注输入"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text == "/cancel_monitor":
        context.user_data.pop("monitor_action", None)
        context.user_data.pop("monitor_temp", None)
        await update.message.reply_text("❌ 已取消添加")
        await monitor_menu_from_message(update, context)
        return ConversationHandler.END

    if text == "/skip":
        note = ""
    else:
        note = text

    temp = context.user_data.get("monitor_temp", {})
    address = temp.get("address", "")
    chain_type = temp.get("chain_type", "")

    if not address:
        await update.message.reply_text("❌ 会话已过期，请重新添加")
        return ConversationHandler.END

    if add_monitored_address(address, chain_type, user_id, note):
        if note:
            await update.message.reply_text(
                f"✅ 已添加监控地址\n\n"
                f"📌 地址：`{address}`\n"
                f"⛓️ 网络：{chain_type}\n"
                f"📝 备注：{note}",
                parse_mode=None
            )
        else:
            await update.message.reply_text(
                f"✅ 已添加监控地址\n\n"
                f"📌 地址：`{address}`\n"
                f"⛓️ 网络：{chain_type}",
                parse_mode=None
            )
    else:
        await update.message.reply_text("❌ 添加失败，地址可能已存在")

    context.user_data.pop("monitor_action", None)
    context.user_data.pop("monitor_temp", None)
    await monitor_menu_from_message(update, context)
    return ConversationHandler.END


async def monitor_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看监控列表（显示备注）"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    addresses = get_monitored_addresses(user_id=user_id)

    if not addresses:
        await query.message.edit_text("📭 您还没有添加任何监控地址，请先添加。")
        await asyncio.sleep(1)
        await monitor_menu(update, context)
        return

    text = "📋 **您的监控地址列表**\n\n"
    for i, addr in enumerate(addresses, 1):
        full_addr = addr['address']
        note = addr.get('note', '')
        text += f"{i}. `{full_addr}` ({addr['chain_type']})\n"
        if note:
            text += f"   📝 备注：{note}\n"
        added_time = datetime.fromtimestamp(addr['added_at'], tz=timezone.utc).astimezone(BEIJING_TZ)
        text += f"   📅 添加时间：{added_time.strftime('%Y-%m-%d %H:%M')}\n\n"

    keyboard = [[InlineKeyboardButton("◀️ 返回", callback_data="monitor_menu")]]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)


async def monitor_remove_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始删除监控地址（显示备注帮助识别）"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    addresses = get_monitored_addresses(user_id=user_id)

    if not addresses:
        await query.message.edit_text("📭 您还没有添加任何监控地址")
        await asyncio.sleep(1)
        await monitor_menu(update, context)
        return

    keyboard = []
    for addr in addresses:
        full_addr = addr['address']
        note = addr.get('note', '')
        short_addr = f"{full_addr[:12]}...{full_addr[-8:]}"
        if note:
            button_text = f"🗑️ {short_addr} ({note})"
        else:
            button_text = f"🗑️ {short_addr}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"monitor_del_{addr['id']}")])

    keyboard.append([InlineKeyboardButton("◀️ 返回", callback_data="monitor_menu")])

    await query.message.edit_text(
        "🗑️ **删除监控地址**\n\n选择要删除的地址：",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return MONITOR_REMOVE


async def monitor_remove_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """确认删除监控地址（只能删除自己的）"""
    query = update.callback_query
    user_id = query.from_user.id
    address_id = int(query.data.split("_")[2])

    # 先检查这个地址是否是当前用户添加的
    addresses = get_monitored_addresses(user_id=user_id)
    is_owner = any(addr['id'] == address_id for addr in addresses)

    if not is_owner:
        await query.answer("❌ 只能删除自己添加的地址", show_alert=True)
        return

    if remove_monitored_address(address_id):
        await query.answer("✅ 已删除")
    else:
        await query.answer("❌ 删除失败")

    await monitor_menu(update, context)
    return ConversationHandler.END


async def monitor_menu_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """从消息返回监控菜单"""
    from handlers.menu import get_main_menu

    addresses = get_monitored_addresses()

    keyboard = [
        [InlineKeyboardButton("➕ 添加监控地址", callback_data="monitor_add")],
        [InlineKeyboardButton("📋 查看监控列表", callback_data="monitor_list")],
        [InlineKeyboardButton("📊 月度统计", callback_data="monitor_stats")],
        [InlineKeyboardButton("❌ 删除监控地址", callback_data="monitor_remove")],
        [InlineKeyboardButton("◀️ 返回主菜单", callback_data="main_menu")]
    ]

    if len(addresses) == 0:
        text = (
            "🔔 **USDT 地址监控**\n\n"
            f"📊 当前监控地址数：**0** 个\n\n"
            "⚠️ 暂无监控地址，请先添加监控地址。"
        )
    else:
        text = (
            "🔔 **USDT 地址监控**\n\n"
            f"📊 当前监控地址数：**{len(addresses)}** 个\n\n"
            "当监控地址有 USDT 交易时，会自动发送通知给管理员和操作员。"
        )

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def monitor_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消监控操作"""
    context.user_data.pop("monitor_action", None)
    context.user_data.pop("monitor_temp", None)
    await update.message.reply_text("❌ 已取消监控操作")
    await monitor_menu_from_message(update, context)
    return ConversationHandler.END


def get_monitor_conversation_handler():
    """获取监控模块的对话处理器"""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(monitor_add_start, pattern="^monitor_add$"),
            CallbackQueryHandler(monitor_remove_start, pattern="^monitor_remove$"),
        ],
        states={
            MONITOR_ADD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, monitor_add_input),
            ],
            MONITOR_ADD_NOTE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, monitor_add_note),
            ],
            MONITOR_REMOVE: [
                CallbackQueryHandler(monitor_remove_confirm, pattern="^monitor_del_"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel_monitor", monitor_cancel),
        ],
        per_message=False,
        allow_reentry=True,
    )

__all__ = [
    'get_address_balance',
    'get_trc20_transactions',
    'get_monthly_stats',
    'check_address_transactions',
    # ... 其他已有导出
]
