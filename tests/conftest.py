"""所有测试默认禁止真实网络。

模拟测试只能证明代码路径，不能证明平台可用；一旦偷偷联网，
就会把「平台端到端」和「模拟」混为一谈，所以这里直接把出口封死。
"""
from __future__ import annotations

import socket

import pytest


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("测试禁止真实网络请求（模拟测试必须离线）")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr("requests.post", blocked)
    monkeypatch.setattr("requests.get", blocked)
    monkeypatch.setattr("requests.Session.request", blocked)
    yield
