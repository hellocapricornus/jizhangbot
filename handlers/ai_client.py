# handlers/ai_client.py - 多 API 自动切换客户端

import aiohttp
import asyncio
from typing import List, Dict, Optional

# 直接从 config.py 导入 API Key
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
        "api_key": DEEPSEEK_API_KEY,  # 直接从 config 读取
        "model": "deepseek-chat",
        "free_quota": 5000000  # 500万 tokens
    },
    {
        "name": "SiliconFlow",
        "url": "https://api.siliconflow.cn/v1/chat/completions",
        "api_key": SILICONFLOW_API_KEY,
        "model": "Qwen/Qwen2-7B-Instruct",
        "free_quota": 20000000  # 2000万 tokens
    },
    {
        "name": "阿里云通义",
        "url": "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
        "api_key": DASHSCOPE_API_KEY,
        "model": "qwen-turbo",
        "free_quota": 5000000  # 500万 tokens/月
    },
    {
        "name": "智谱AI",
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "api_key": ZHIPU_API_KEY,
        "model": "glm-4-flash",
        "free_quota": 5000000  # 500万 tokens
    }
]

# 过滤掉没有配置 Key 的
API_CONFIGS = [c for c in API_CONFIGS if c["api_key"]]

class AIClient:
    """多 API 自动切换客户端"""

    def __init__(self, configs: List[Dict] = None):
        self.configs = configs or API_CONFIGS
        self.current_index = 0
        self.failed_keys = set()

    async def chat(self, prompt: str, system_prompt: str = "你是一个智能助手，回答问题要简洁、准确、友好。") -> str:
        """发送对话请求，自动切换 API"""
        errors = []

        for i, config in enumerate(self.configs):
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

                # 如果是余额不足或配额问题，标记失败并切换
                if "insufficient" in error_msg.lower() or "quota" in error_msg.lower() or "balance" in error_msg.lower():
                    self.failed_keys.add(config["name"])
                    print(f"⚠️ {config['name']} 配额不足，已自动切换到下一个")

                continue

        # 所有 API 都失败
        return f"❌ 所有 AI 服务暂时不可用，请稍后再试。\n错误: {', '.join(errors)}"

    async def _call_api(self, config: Dict, prompt: str, system_prompt: str) -> str:
        """调用单个 API"""
        name = config["name"]
        url = config["url"]
        api_key = config["api_key"]

        print(f"🤖 正在使用 {name} API...")

        headers = {
            "Content-Type": "application/json"
        }

        # 不同 API 的请求格式不同
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

                # 解析不同 API 的响应格式
                if name == "DeepSeek" or name == "SiliconFlow" or name == "智谱AI":
                    return data["choices"][0]["message"]["content"]
                elif name == "阿里云通义":
                    return data["output"]["choices"][0]["message"]["content"]
                else:
                    return str(data)


# 全局客户端实例
ai_client = None

def get_ai_client() -> AIClient:
    global ai_client
    if ai_client is None:
        ai_client = AIClient()
    return ai_client
