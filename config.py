import os
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("ACCOUNTING_BOT_TOKEN")
OWNER_ID = int(os.getenv("ACCOUNTING_OWNER", "0"))
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY", "")
