"""平台适配器注册表。加平台就在这里加一行，不做插件框架。"""
from __future__ import annotations

from .douyin import DouyinAdapter
from .wechat import WechatAdapter

ADAPTERS = {
    "douyin": DouyinAdapter,
    "wechat": WechatAdapter,
}


def get_adapter(platform: str):
    try:
        return ADAPTERS[platform]
    except KeyError as exc:
        raise NotImplementedError(f"没有 {platform} 的适配器") from exc
