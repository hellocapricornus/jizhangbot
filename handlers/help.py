# handlers/help.py
from telegram import Update
from telegram.ext import ContextTypes
from handlers.menu import get_main_menu

async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """发送使用说明"""
    user_id = update.effective_user.id
    text = (
        "📚 <b>记账机器人操作说明</b>\n\n"

        "<blockquote><b>1️⃣ 基础设置</b></blockquote>\n"
        "增加记员 ▫️ <code>添加操作人 @aaa @bbb</code>添加临时操作人\n"
        "删除记员 ▫️ <code>删除操作人 @aaa @bbb</code>删除临时操作人\n"
        "增加记员 ▫️ 回复指定人消息：<code>添加操作人</code>\n"
        "删除记员 ▫️ 回复指定人消息：<code>删除操作人</code>\n\n"

        "<blockquote><b>2️⃣ 入款操作</b></blockquote>\n"
        "普通入款 ▫️ <code>+1000</code>\n"
        "临时汇率 ▫️ <code>+1000/7.3</code>\n"
        "临时手续费 ▫️ <code>+1000*5</code>\n"
        "临时单笔费用 ▫️ <code>+1000#10</code>\n"
        "组合模式 ▫️ <code>+1000*5/7.2#10</code>顺序不可打乱\n"
        "带分类入款 ▫️ <code>+1000 德国</code>\n"
        "完整模式 ▫️ <code>+1000*5/7.2 德国</code>\n"
        "修正入款 ▫️ <code>-500</code>\n\n"

        "<blockquote><b>3️⃣ 出款操作</b></blockquote>\n"
        "普通出款 ▫️ <code>下发100u</code>\n"
        "修正出款 ▫️ <code>下发-50u</code>\n\n"

        "<blockquote><b>4️⃣ 群组配置</b></blockquote>\n"
        "设置费率 ▫️ <code>设置手续费5</code>\n"
        "设置汇率 ▫️ <code>设置汇率7.2</code>\n"
        "设置单笔费用 ▫️ <code>设置单笔费用2</code>\n"
        "组合设置 ▫️ <code>设置手续费2 设置汇率20 设置单笔费用15</code>\n"
        "组合设置 ▫️ <code>设置手续费2 汇率20 单笔费用15</code>\n"
        "查看配置 ▫️ <code>查看配置</code>\n\n"

        "<blockquote><b>5️⃣ 单独配置（指定人）</b></blockquote>\n"
        "设置配置 ▫️ <code>设置 @用户名 手续费5 汇率10 单笔费用12</code>\n"
        "设置配置 ▫️ 回复指定人消息：<code>设置手续费5 汇率10</code>\n"
        "删除配置 ▫️ <code>删除 @用户名 配置</code>\n"
        "删除配置 ▫️ 回复指定人消息：<code>删除配置</code>\n\n"

        "<blockquote><b>6️⃣ 账单查询</b></blockquote>\n"
        "当前账单 ▫️ <code>当前账单</code>\n"
        "今日统计 ▫️ <code>今日总</code>\n"
        "总计统计 ▫️ <code>总</code>\n"
        "按日期查询 ▫️ <code>查询账单</code>（选择年月日）\n"
        "导出账单 ▫️ <code>导出账单</code>（生成HTML文件）\n"
        "结束账单 ▫️ <code>结束账单</code>（保存并重置配置）\n\n"

        "<blockquote><b>7️⃣ 账单管理</b></blockquote>\n"
        "清理账单 ▫️ <code>清理账单</code>（清空当前）\n"
        "清理全部 ▫️ <code>清理总账单</code>（清空历史）\n"
        "移除上一笔 ▫️ <code>移除上一笔</code>\n"
        "撤销指定 ▫️ 回复记账消息：<code>撤销账单</code>\n\n"

        "<blockquote><b>🔍 USDT查询</b></blockquote>\n"
        "查余额 ▫️ 群内发送TRC20/ERC20地址自动查询\n"
        "监控地址 ▫️ 私聊「USDT监控」菜单管理\n"
        "转账查询 ▫️ 私聊「互转查询」分析地址间关系\n\n"

        "<blockquote><b>📢 群发功能</b></blockquote>\n"
        "群发消息 ▫️ 私聊「群发」向多个群发送消息\n"
        "支持类型 ▫️ 文字、图片、视频、文件、GIF\n\n"

        "<blockquote><b>📁 群组管理</b></blockquote>\n"
        "群组统计 ▫️ 按分类统计群组数量\n"
        "创建分类 ▫️ 私聊「群组管理」创建分类\n"
        "设置分类 ▫️ 为群组设置分类标签\n\n"

        "<blockquote><b>🤖 AI 对话</b></blockquote>\n"
        "群内提问 ▫️ <code>@机器人 你的问题</code>临时操作人不可用\n"
        "私聊提问 ▫️ 直接发送问题\n"
        "数据查询 ▫️ 支持查询账单、群组、操作员等\n\n"

        "<blockquote><b>🧮 计算器</b></blockquote>\n"
        "基础运算 ▫️ <code>100+200</code>\n"
        "复杂运算 ▫️ <code>(10+5)*3</code>\n"
        "数学函数 ▫️ <code>sqrt(100)</code> <code>2^3</code>\n\n"

        "<blockquote><b>👤 个人中心</b></blockquote>\n"
        "个人统计 ▫️ 查看个人记账汇总\n"
        "监控地址 ▫️ 管理自己的监控地址\n"
        "交易提醒 ▫️ 开关地址交易通知\n"
        "群发附言 ▫️ 设置默认群发签名\n"
        "每日早报 ▫️ 开启/关闭每日早报\n"
        "数据分析 ▫️ 导出数据分析报告\n"
        "会员系统 ▫️ 升级/续费会员\n\n"

        "<blockquote><b>🛡️ 权限等级</b></blockquote>\n"
        "👨‍💼 管理员 ▫️ 所有功能 + 管理操作员\n"
        "👥 正式操作员 ▫️ 除管理员管理外的所有功能\n"
        "🧑‍💻 临时操作员 ▫️ 仅记账、地址查询、计算器\n"
        "🙍 普通用户 ▫️ 查看帮助、个人中心、联系管理员\n\n"

        "💎 <code>▫️</code>后的文字可长按复制指令\n"
        "💎 使用 /start 返回主菜单"
    )

    await update.message.reply_text(
        text,
        parse_mode='HTML',
        reply_markup=get_main_menu(user_id)
    )
