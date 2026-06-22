"""配置同步并发互斥测试（审查 M5，离线确定性）。

run_config_sync 取 lock:config_sync 串行：已有同步在跑时第二次调用直接跳过，不触发 EMS 拉取，
避免首连/定时/手动并发基于过期快照交叉失活。
"""
from __future__ import annotations

from typing import cast

from app.core.constants import REDIS_CONFIG_SYNC_LOCK
from app.ems.client import EmsClient
from app.sync import config_sync


class _StubClient:
    """记录是否被调用的桩 client；被调用即说明未被锁拦截。"""

    def __init__(self) -> None:
        self.called = False

    async def get_space_list(self):
        self.called = True
        return []


async def test_run_config_sync_skips_when_locked(fake_redis) -> None:
    # 预先占用锁，模拟已有同步在跑
    await fake_redis.set(REDIS_CONFIG_SYNC_LOCK, "other-owner")
    client = _StubClient()

    result = await config_sync.run_config_sync(cast(EmsClient, client))

    assert result.skipped is True  # 跳过本轮
    assert client.called is False  # 未发起任何 EMS 拉取
    # 不得误删他人持有的锁
    assert await fake_redis.get(REDIS_CONFIG_SYNC_LOCK) == "other-owner"
