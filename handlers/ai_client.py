# handlers/ai_client.py - 完整正确版

import aiohttp
import asyncio
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

    # ai_client.py - 简化 chat_with_data 方法

    async def chat_with_data(self, prompt: str, group_id: str = None, 
                              user_id: int = None,
                              system_prompt: str = None) -> str:
        """支持数据查询的对话（简化版）"""

        # 收集数据
        from db import get_all_groups_from_db, get_groups_by_category
        from handlers.accounting import accounting_manager

        groups = get_all_groups_from_db()
        group_count = len(groups)

        # 构建简洁提示词
        if system_prompt is None:
            if group_id:
                system_prompt = f"""你是记账助手。机器人已加入{group_count}个群。回答要简洁友好。"""
            else:
                system_prompt = f"""你是记账助手。机器人已加入{group_count}个群。回答要简洁友好。"""

        return await self.chat(prompt, system_prompt)

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
                "max_tokens": 1000,
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
                    "max_tokens": 1000,
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
