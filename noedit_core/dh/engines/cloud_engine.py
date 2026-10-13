# -*- coding: utf-8 -*-
"""云端数字人引擎桥接（Azure / 腾讯云 / 阿里云）。

配置文件 dh/cloud_config.json（从 cloud_config.example.json 复制）：
{
  "provider": "azure" | "tencent" | "aliyun",
  "azure":   {"region": "...", "key": "...", "voice": "...", "avatar_id": "..."},
  "tencent": {"secret_id": "...", "secret_key": "...", "avatar_id": "..."},
  "aliyun":  {"access_key": "...", "secret": "...", "avatar_id": "..."}
}

本引擎只提供统一桥接骨架：具体 HTTP 签名各家不同，按各自 SDK 示例在
provider 对应分支里补 submit/poll/download 三步即可。
"""
from __future__ import annotations

import json
import os
from typing import Optional

from .base import Engine, EngineError

_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_HERE, "..", "cloud_config.json")
EXAMPLE_PATH = os.path.join(_HERE, "..", "cloud_config.example.json")


def load_config() -> Optional[dict]:
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


class CloudEngine(Engine):
    name = "cloud"

    def check(self) -> str:
        cfg = load_config()
        if not cfg:
            return "no config set (copy cloud_config.example.json -> cloud_config.json)"
        if not cfg.get("provider"):
            return "config missing provider"
        # 三家 provider 的 submit/poll/download 还没落地，这里就不回报 'ok'：
        # 否则 dh_status 一片绿、调用即报错，比直接说清楚更坑。
        return ("配置就绪，但 %s 桥接未接入（在 cloud_engine.py::_%s 补 submit/poll/download）"
                % (cfg["provider"], cfg["provider"]))

    def generate(self, image: str, audio: str, out_path: str, **kw) -> str:
        status = self.check()
        if status != "ok":
            raise EngineError("cloud 引擎不可用: %s" % status)
        cfg = load_config()
        provider = cfg["provider"]
        if provider == "azure":
            return self._azure(cfg.get("azure") or {}, image, audio, out_path, **kw)
        if provider == "tencent":
            return self._tencent(cfg.get("tencent") or {}, image, audio, out_path, **kw)
        if provider == "aliyun":
            return self._aliyun(cfg.get("aliyun") or {}, image, audio, out_path, **kw)
        raise EngineError("未知 provider: %s" % provider)

    # ---------- 各 provider 骨架（submit → poll → download） ----------
    def _azure(self, conf, image, audio, out_path, **kw):
        raise EngineError(
            "Azure Speech Avatar 桥接未接入：请在 cloud_engine.py::_azure 中"
            "按 https://learn.microsoft.com/azure/ai-services/speech-service 官方 SDK 示例"
            "补 submit/poll/download 三步（付费服务，需自行开通并填 key）")

    def _tencent(self, conf, image, audio, out_path, **kw):
        raise EngineError(
            "腾讯云智能数智人桥接未接入：请在 cloud_engine.py::_tencent 中"
            "按腾讯云 SDK 示例补签名调用（付费服务，需自行开通并填 key）")

    def _aliyun(self, conf, image, audio, out_path, **kw):
        raise EngineError(
            "阿里云通义数字人桥接未接入：请在 cloud_engine.py::_aliyun 中"
            "按阿里云 SDK 示例补签名调用（付费服务，需自行开通并填 key）")


def register_self():
    from . import register as _reg
    _reg("cloud", CloudEngine)


register_self()
