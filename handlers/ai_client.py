# handlers/ai_client.py - 完整正确版（支持数据提供者）

import aiohttp
import asyncio
import json
from typing import List, Dict, Optional

from config import (
    DEEPSEEK_API_KEY,
    SILICONFLOW_API_KEY,
    DASHSCOPE_API_KEY,
    ZHIPU_API_KEY
)

API_CONFIGS = [
    {
        "name": "DeepSeek",
        "url": "https://api.deepseek.com/v1/chat/completions",
        "api_key": DEEPSEEK_API_KEY,
        "model": "deepseek-chat",
        "free_quota": 5000000
    },
    {
        "name": "SiliconFlow",
        "url": "https://api.siliconflow.cn/v1/chat/completions",
        "api_key": SILICONFLOW_API_KEY,
        "model": "Qwen/Qwen2-7B-Instruct",
        "free_quota": 20000000
    },
    {
        "name": "阿里云通义",
        "url": "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
        "api_key": DASHSCOPE_API_KEY,
        "model": "qwen-turbo",
        "free_quota": 5000000
    },
    {
        "name": "智谱AI",
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "api_key": ZHIPU_API_KEY,
        "model": "glm-4-flash",
        "free_quota": 5000000
    }
]

API_CONFIGS = [c for c in API_CONFIGS if c["api_key"]]


class AIClient:
    """多 API 自动切换客户端"""

    def __init__(self, configs: List[Dict] = None):
        self.configs = configs or API_CONFIGS
        self.current_index = 0
        self.failed_keys = set()

    async def chat(self, prompt: str, system_prompt: str = "你是一个智能助手，回答问题要简洁、准确、友好。") -> str:
        """普通对话"""
        errors = []
        for config in self.configs:
            if not config.get("api_key"):
                continue
            if config["name"] in self.failed_keys:
                continue
            try:
                result = await self._call_api(config, prompt, system_prompt)
                return result
            except Exception as e:
                error_msg = str(e)
                errors.append(f"{config['name']}: {error_msg[:50]}")
                if "insufficient" in error_msg.lower() or "quota" in error_msg.lower() or "balance" in error_msg.lower():
                    self.failed_keys.add(config["name"])
                continue
        return f"❌ 所有 AI 服务暂时不可用，请稍后再试。\n错误: {', '.join(errors)}"

    async def chat_with_data(self, prompt: str, group_id: str = None, 
                              user_id: int = None,
                              system_prompt: str = None) -> str:
        """
        支持数据查询的对话 - 让 AI 读取数据库中的数据并分析回答
        """
        from handlers.data_provider import data_provider

        # 🔥 检测是否需要导出详细记录
        is_export = any(word in prompt for word in ["导出", "详细", "明细", "列出", "所有记录", "每一笔", "详细账单", "原始账单"])

        # 第一步：让 AI 分析需要什么数据
        intent = await self._identify_intent(prompt)

        print(f"[DEBUG] AI 意图识别结果: {intent}")
        print(f"[DEBUG] 是否导出模式: {is_export}")

        # 如果是不需要数据的普通对话
        if intent.get("type") == "unknown" or intent.get("type") == "chat":
            return await self.chat(prompt)

        # 第二步：获取数据
        data = await self._fetch_data(intent, data_provider)

        if data.get("error"):
            return f"❌ {data['error']}"

        # 🔥 如果是导出模式，直接返回原始账单格式（不经过 AI 总结）
        if is_export:
            return await self._export_raw_bill(prompt, data, intent)

        # 第三步：让 AI 分析数据并回答
        answer = await self._generate_answer(prompt, data, intent)

        return answer

    async def _export_raw_bill(self, question: str, data: Dict, intent: Dict) -> str:
        """导出原始账单（直接使用 data_provider 的格式化函数）"""

        intent_type = intent.get("type", "unknown")

        # 群组账单导出 - 使用 data_provider 中已有的格式化函数
        if intent_type == "group_bill":
            return self._format_group_bill_export(data)

        # 地址统计导出
        elif intent_type == "address_stats":
            return self._format_address_export(data)

        # 其他类型 - 直接返回原始数据
        else:
            return f"📊 查询结果：\n```json\n{json.dumps(data, ensure_ascii=False, indent=2, default=str)}\n```"


    def _format_group_bill_export(self, data: Dict) -> str:
        """格式化群组账单导出 - 直接输出原始账单"""

        if data.get("error"):
            return f"❌ {data['error']}"

        if data.get("message"):
            return f"📭 {data['message']}"

        group_name = data.get("group_name", "未知群组")
        date = data.get("date", "未知日期")
        fee_rate = data.get("fee_rate", 0)
        exchange_rate = data.get("exchange_rate", 1)
        per_transaction_fee = data.get("per_transaction_fee", 0)

        result = f"📊 **{group_name} {date} 详细账单**\n\n"
        result += f"⚙️ 费率：{fee_rate}%\n"
        result += f"💱 汇率：1 USDT = {exchange_rate} 元\n"
        result += f"📝 单笔费用：{per_transaction_fee} 元\n\n"

        # 入款记录
        income_records = data.get("recent_income", [])
        if income_records:
            result += f"💰 **入款记录（{len(income_records)}笔）**\n"
            result += "```\n"
            result += f"{'时间':<8} {'金额(元)':<12} {'USDT':<10} {'用户':<15} {'分类'}\n"
            result += "-" * 55 + "\n"
            for r in income_records:
                time_str = r.get("time", "")
                amount_cny = r.get("amount_cny", 0)
                amount_usdt = r.get("amount_usdt", 0)
                user = r.get("user", "")[:12]
                category = r.get("category", "")
                result += f"{time_str:<8} {amount_cny:<12.2f} {amount_usdt:<10.2f} {user:<15} {category}\n"
            result += "```\n\n"

        # 出款记录
        expense_records = data.get("recent_expense", [])
        if expense_records:
            result += f"📤 **出款记录（{len(expense_records)}笔）**\n"
            result += "```\n"
            result += f"{'时间':<8} {'USDT':<10} {'用户':<15}\n"
            result += "-" * 35 + "\n"
            for r in expense_records:
                time_str = r.get("time", "")
                amount_usdt = r.get("amount_usdt", 0)
                user = r.get("user", "")[:12]
                result += f"{time_str:<8} {amount_usdt:<10.2f} {user:<15}\n"
            result += "```\n\n"

        # 分类统计
        categories = data.get("categories", {})
        if categories:
            result += f"📁 **入款分组统计**\n"
            for cat, cat_data in categories.items():
                result += f"  • {cat}：{cat_data.get('cny', 0):.2f}元 = {cat_data.get('usdt', 0):.2f} USDT（{cat_data.get('count', 0)}笔）\n"
            result += "\n"

        # 汇总
        result += f"📊 **汇总**\n"
        result += f"  • 总入款：{data.get('income_cny', 0):.2f}元 = {data.get('income_usdt', 0):.2f} USDT（{data.get('income_count', 0)}笔）\n"
        result += f"  • 总出款：{data.get('expense_usdt', 0):.2f} USDT（{data.get('expense_count', 0)}笔）\n"
        result += f"  • 待下发：{data.get('pending_usdt', 0):.2f} USDT\n"

        return result


    def _format_address_export(self, data: Dict) -> str:
        """格式化地址导出"""

        if data.get("error"):
            return f"❌ {data['error']}"

        address = data.get("address", "未知地址")
        note = data.get("note", "")
        date = data.get("date", "未知日期")

        result = f"💰 **监控地址收支详情**\n\n"
        result += f"📌 地址：`{address}`\n"
        if note:
            result += f"📝 备注：{note}\n"
        result += f"📅 日期：{date}\n\n"

        result += f"📊 **统计**\n"
        result += f"  • 收到：{data.get('received_usdt', 0):.2f} USDT\n"
        result += f"  • 转出：{data.get('sent_usdt', 0):.2f} USDT\n"
        result += f"  • 净收入：{data.get('net_usdt', 0):.2f} USDT\n"
        result += f"  • 当前余额：{data.get('balance_usdt', 0):.2f} USDT\n"
        result += f"  • 交易笔数：{data.get('transaction_count', 0)} 笔\n"

        return result

    async def _identify_intent(self, prompt: str) -> Dict:
        """识别用户意图，确定需要什么数据"""

        intent_prompt = f"""分析用户问题，判断需要查询什么数据。

用户问题：{prompt}

重要规则：
1. 如果用户提到"备注为XXX"、"备注XXX"、"叫XXX的地址"、"XXX地址"，说明用户想查询监控地址
2. 此时 type 应该是 "address_stats"
3. params 中应该用 "address_note" 字段记录备注名称，而不是 "address"
   例如："查询备注为测试的监控地址" -> {{"type": "address_stats", "params": {{"address_note": "测试", "period": "today"}}}}

可选的数据类型：
- group_bill: 查询某个群组的账单（需要 group_name，可能指定 date）
- today_all_income: 查询所有群组今日收入情况
- group_count: 查询群组数量
- group_categories: 查询群组分类
- today_joined: 查询今天新加入的群组
- monthly_joined: 查询本月每天新加入的群组
- top_users: 查询今日入款最多的用户
- active_users: 查询今日使用记账的用户
- active_groups: 查询今日有交易的群组
- top_group: 查询今日交易最多的群组
- activity_ranking: 查询群组活跃度排行
- pending_groups: 查询有待下发的群组
- large_transactions: 查询大额交易
- hourly_distribution: 查询时段分布
- week_comparison: 查询本周vs上周对比
- month_total: 查询本月总收入
- category_percentage: 查询各分类入款占比
- weekly_trend: 查询最近7天趋势
- monitored_addresses: 查询监控地址列表
- address_stats: 查询某个地址的收支统计（用 address_note 记录备注名称，或用 address 记录完整地址）
- operators: 查询操作员列表
- group_config: 查询群组配置（费率/汇率）
- groups_by_category: 查询某个分类下的所有群组名称
- all_groups_by_category: 获取所有分类及其下的群组列表
- chat: 普通对话，不需要数据
- unknown: 无法识别

返回 JSON 格式：
{{"type": "数据类型", "params": {{"key": "value"}}}}

示例：
- "测试5群今天收入多少" -> {{"type": "group_bill", "params": {{"group_name": "测试5群", "date": "today"}}}}
- "测试5群昨天账单" -> {{"type": "group_bill", "params": {{"group_name": "测试5群", "date": "yesterday"}}}}
- "今天哪个群组收入最多" -> {{"type": "top_group", "params": {{}}}}
- "最近一周收入趋势" -> {{"type": "weekly_trend", "params": {{}}}}
- "操作员有哪些" -> {{"type": "operators", "params": {{}}}}
- "查询备注为测试的监控地址今天的收支情况" -> {{"type": "address_stats", "params": {{"address_note": "测试", "period": "today"}}}}
- "监控地址列表" -> {{"type": "monitored_addresses", "params": {{}}}}
- "中国分类下有哪些群" -> {{"type": "groups_by_category", "params": {{"category": "中国"}}}}
- "所有群的分类下分别有哪些群组" -> {{"type": "all_groups_by_category", "params": {{}}}}
- "你好" -> {{"type": "chat", "params": {{}}}}

只返回 JSON，不要其他内容。"""

        try:
            response = await self.chat(intent_prompt, "你是一个意图识别助手，只返回 JSON")
            # 提取 JSON
            start = response.find('{')
            end = response.rfind('}') + 1
            if start != -1 and end != 0:
                json_str = response[start:end]
                return json.loads(json_str)
        except Exception as e:
            print(f"[DEBUG] 意图识别失败: {e}")

        return {"type": "unknown", "params": {}}

    async def _fetch_data(self, intent: Dict, data_provider) -> Dict:
        """根据意图获取数据"""

        intent_type = intent.get("type", "unknown")
        params = intent.get("params", {})

        # 群组账单
        if intent_type == "group_bill":
            group_name = params.get("group_name", "")
            date = params.get("date", "today")

            if not group_name:
                return {"error": "请指定群组名称"}

            if date == "today":
                return data_provider.get_group_today_bill(group_name)
            elif date == "yesterday":
                from datetime import datetime, timedelta
                from handlers.data_provider import BEIJING_TZ
                yesterday = (datetime.now(BEIJING_TZ) - timedelta(days=1)).strftime('%Y-%m-%d')
                return data_provider.get_group_bill_by_date(group_name, yesterday)
            else:
                return data_provider.get_group_bill_by_date(group_name, date)

        # 今日所有群组收入
        elif intent_type == "today_all_income":
            return data_provider.get_today_all_income()

        # 群组数量
        elif intent_type == "group_count":
            return data_provider.get_group_count()

        # 群组分类
        elif intent_type == "group_categories":
            return data_provider.get_group_categories()

        # 今日新加入群组
        elif intent_type == "today_joined":
            return data_provider.get_today_joined_groups()

        # 本月每天新加入
        elif intent_type == "monthly_joined":
            return data_provider.get_monthly_joined_groups()

        # 今日入款最多的用户
        elif intent_type == "top_users":
            limit = params.get("limit", 10)
            return data_provider.get_today_top_users(limit)

        # 今日活跃用户
        elif intent_type == "active_users":
            return data_provider.get_today_active_users()

        # 今日活跃群组
        elif intent_type == "active_groups":
            return data_provider.get_today_active_groups()

        # 今日交易最多的群组
        elif intent_type == "top_group":
            return data_provider.get_today_top_group()

        # 群组活跃度排行
        elif intent_type == "activity_ranking":
            return data_provider.get_group_activity_ranking()

        # 待下发群组
        elif intent_type == "pending_groups":
            return data_provider.get_pending_usdt_groups()

        # 大额交易
        elif intent_type == "large_transactions":
            threshold = params.get("threshold", 5000)
            return data_provider.get_large_transactions(threshold)

        # 时段分布
        elif intent_type == "hourly_distribution":
            return data_provider.get_hourly_distribution()

        # 周对比
        elif intent_type == "week_comparison":
            return data_provider.get_week_comparison()

        # 本月总收入
        elif intent_type == "month_total":
            return data_provider.get_month_total_income()

        # 分类占比
        elif intent_type == "category_percentage":
            return data_provider.get_category_income_percentage()

        # 周趋势
        elif intent_type == "weekly_trend":
            return data_provider.get_weekly_trend()

        # 监控地址列表
        elif intent_type == "monitored_addresses":
            return data_provider.get_monitored_addresses_list()

        # 地址统计
        elif intent_type == "address_stats":
            address = params.get("address", "")
            address_note = params.get("address_note", "")  # 🔥 新增：支持 address_note
            period = params.get("period", "today")

            # 🔥 优先使用 address_note
            if address_note:
                from db import get_monitored_addresses
                addresses = get_monitored_addresses()
                found_addr = None
                for a in addresses:
                    note = a.get('note', '')
                    if note and (address_note == note or address_note in note or note in address_note):
                        found_addr = a['address']
                        break

                if found_addr:
                    address = found_addr
                    print(f"[DEBUG] 备注「{address_note}」对应地址: {address}")
                else:
                    return {"error": f"未找到备注为「{address_note}」的监控地址"}

            # 如果没有 address_note，尝试从 address 字段提取备注
            if not address and params.get("address"):
                raw_address = params.get("address", "")
                if any('\u4e00' <= c <= '\u9fff' for c in raw_address):
                    import re
                    note_match = re.search(r'备注[为:：]?\s*["\']?([^"\'，,]+)', raw_address)
                    if not note_match:
                        note_match = re.search(r'([^"\'，,]{2,})的?地址', raw_address)
                    if note_match:
                        address_note = note_match.group(1).strip()
                        from db import get_monitored_addresses
                        addresses = get_monitored_addresses()
                        for a in addresses:
                            if a.get('note', '') == address_note:
                                address = a['address']
                                break
                        if not address:
                            return {"error": f"未找到备注为「{address_note}」的监控地址"}

            if not address:
                return {"error": "请指定地址或备注名称"}

            # 正常查询
            if period == "today":
                return data_provider.get_address_today_stats(address)
            else:
                return data_provider.get_address_stats_by_period(address, period)

        # 操作员列表
        elif intent_type == "operators":
            return data_provider.get_operators()

        # 群组配置
        elif intent_type == "group_config":
            group_name = params.get("group_name", None)
            return data_provider.get_group_config(group_name)

        # 🔥 新增：查询指定分类下的群组列表
        elif intent_type == "groups_by_category":
            category = params.get("category", "")
            if not category:
                return {"error": "请指定分类名称"}
            return data_provider.get_groups_by_category(category)

        elif intent_type == "all_groups_by_category":
            return data_provider.get_all_groups_by_category()

        # 普通对话
        elif intent_type == "chat":
            return {"type": "chat"}

        else:
            return {"error": f"无法识别的问题类型: {intent_type}"}

    async def _generate_answer(self, question: str, data: Dict, intent: Dict) -> str:
        """让 AI 根据数据生成回答"""

        # 如果是普通对话
        if data.get("type") == "chat":
            return await self.chat(question)

        # 如果有错误
        if data.get("error"):
            return f"❌ {data['error']}"

        analysis_prompt = f"""用户问题：{question}

查询到的数据：
{json.dumps(data, ensure_ascii=False, indent=2, default=str)}

请根据这些数据回答用户的问题。要求：
1. 用自然、友好的语言回答
2. 从数据中提取关键信息
3. 如果数据中包含多个项目，进行对比分析
4. 回答要简洁明了
5. 可以适当添加表情符号
6. 不要输出 JSON 格式

回答："""

        return await self.chat(analysis_prompt, "你是记账助手，根据数据回答用户问题")

    async def _call_api(self, config: Dict, prompt: str, system_prompt: str) -> str:
        """调用单个 API"""
        name = config["name"]
        url = config["url"]
        api_key = config["api_key"]

        print(f"🤖 正在使用 {name} API...")

        headers = {"Content-Type": "application/json"}

        if name == "DeepSeek" or name == "SiliconFlow" or name == "智谱AI":
            headers["Authorization"] = f"Bearer {api_key}"
            payload = {
                "model": config["model"],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "stream": False,
                "max_tokens": 2000,  # 增加 token 限制
                "temperature": 0.7
            }
        elif name == "阿里云通义":
            headers["Authorization"] = f"Bearer {api_key}"
            payload = {
                "model": config["model"],
                "input": {
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ]
                },
                "parameters": {
                    "max_tokens": 2000,  # 增加 token 限制
                    "temperature": 0.7
                }
            }
        else:
            raise ValueError(f"未知的 API: {name}")

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=30) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise Exception(f"HTTP {resp.status}: {error_text[:100]}")
                data = await resp.json()
                if name == "DeepSeek" or name == "SiliconFlow" or name == "智谱AI":
                    return data["choices"][0]["message"]["content"]
                elif name == "阿里云通义":
                    return data["output"]["choices"][0]["message"]["content"]
                else:
                    return str(data)


ai_client = None

def get_ai_client() -> AIClient:
    global ai_client
    if ai_client is None:
        ai_client = AIClient()
    return ai_client
