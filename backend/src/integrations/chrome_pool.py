"""Chrome Browser Pool — 轮询分配多个 Chrome CDP 实例给并发任务。

配置（.env）：
    CDP_PORT_BASE=9222        # 第一个实例端口，后续实例依次 +1
    CDP_POOL_SIZE=1           # 实例数量，默认 1（单实例退化为原有行为）
    RESEARCH_CHROME_PROFILE_BASE=/home/xxx/research-chrome-profile
                              # profile 目录前缀，实例 i 用 {base}-{i}
                              # 若不设，沿用 RESEARCH_CHROME_PROFILE（单实例兼容）

用法（orchestrator）：
    from ..integrations.chrome_pool import chrome_pool
    cdp_port = chrome_pool.assign(task_id)   # 轮询拿到一个端口
    # 后续所有 cad_tools 调用传入 cdp_port=cdp_port
"""
from __future__ import annotations

import os


class ChromePool:
    def __init__(self) -> None:
        self._port_base = int(os.environ.get("CDP_PORT_BASE", os.environ.get("CDP_PORT", "9222")))
        self._size = int(os.environ.get("CDP_POOL_SIZE", "1"))
        self._counter = 0

    @property
    def size(self) -> int:
        return self._size

    def assign(self, task_id: int) -> int:
        """轮询返回分配给此任务的 CDP 端口号。"""
        idx = self._counter % self._size
        self._counter += 1
        return self._port_base + idx


# 全局单例，main.py lifespan 中已自动从环境变量初始化
chrome_pool = ChromePool()
