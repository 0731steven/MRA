"""快速测试 chat 接口是否能流式返回内容。运行前确保后端已启动。"""
import asyncio
import os
import sys
from pathlib import Path

# 加载 .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import httpx

BASE = "http://localhost:8101"

async def main():
    # 1. dev-login
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        r = await c.post("/api/auth/dev-login", json={"feishu_user_id": "admin", "name": "Admin"})
        print("login:", r.status_code, r.text[:200])
        if r.status_code != 200:
            return
        token = r.json()["token"]

    headers = {"Authorization": f"Bearer {token}"}

    # 2. 列出已有 reports
    async with httpx.AsyncClient(base_url=BASE, timeout=30, headers=headers) as c:
        r = await c.get("/api/questions")
        print("questions:", r.status_code, r.text[:300])

        # 列 reports — 试几个 id
        for rid in range(1, 6):
            r2 = await c.get(f"/api/reports/{rid}")
            print(f"  report {rid}:", r2.status_code, r2.text[:80])
        report_id = 1

    # 3. 发送 chat 消息，读 SSE
    print(f"\n--- 向 report {report_id} 发送问题 ---")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
    print(f"provider=deepseek  model={model}")
    print(f"base_url={os.environ.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')}")
    print(f"api_key_configured={bool(os.environ.get('DEEPSEEK_API_KEY'))}")
    print()

    async with httpx.AsyncClient(base_url=BASE, timeout=120, headers=headers) as c:
        async with c.stream(
            "POST",
            f"/api/reports/{report_id}/chat",
            json={"message": "报告的主要结论是什么？"},
        ) as resp:
            print("status:", resp.status_code)
            if resp.status_code != 200:
                body = await resp.aread()
                print("error body:", body.decode())
                return
            chunks = 0
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    import json
                    data = json.loads(line[5:].strip())
                    if "error" in data:
                        print("\n[ERROR]", data["error"])
                        return
                    if "delta" in data:
                        print(data["delta"], end="", flush=True)
                        chunks += 1
                    if "done" in data:
                        print(f"\n\n[done] {chunks} chunks received")
                        return
            print(f"\n[stream ended] {chunks} chunks")

asyncio.run(main())
