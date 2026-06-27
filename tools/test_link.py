"""测试消息链接生成逻辑"""
import asyncio, re, sys
sys.path.insert(0, "/opt/tg-signpulse")

# 模拟一段消息文本
test_texts = [
    """📨 新的抽奖已经创建
抽奖信息
  抽奖 ID：abc-123
🔗 https://t.me/c/3734280863/60572""",

    """普通消息没有链接""",

    """Task: 开注
Chat: AFUN
Keyword: 开注
自由注册已经开放
🔗 https://t.me/c/2626018568/236""",
]

for t in test_texts:
    m = re.search(r'🔗\s*(https://t\.me/c/\d+/\d+)', t)
    if m:
        print(f"MATCH: {m.group(1)}")
    else:
        print(f"NO MATCH in: {t[:60]}...")
print("DONE")
