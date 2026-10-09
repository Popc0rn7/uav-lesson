"""Jev Decisions API 客户端，以及三种问题的构造函数。"""

import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

OPENROUTER_URL = "https://openrouter.ai/api/alpha/decisions"


class JevClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "typesafe/jev-1.13",
        timeout: float = 30,
    ) -> None:
        load_dotenv(Path(__file__).with_name(".env"))
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("请在 .env、环境变量或 api_key 参数中设置 OPENROUTER_API_KEY")
        self.model = model
        self.timeout = timeout

    def request(
        self, questions: dict[str, Any], state: str | dict | list
    ) -> dict[str, Any]:
        """提交一个 state 和多个问题，返回完整响应（含 answers 和 usage）。

        state 为文本、JSON 对象或数组；HTTP/网络异常由 requests 抛出。
        """
        response = requests.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "state": state, "questions": questions},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


def make_noul(name: str, instruction: str, criteria: dict[str, str]) -> dict:
    """构造是非问题；criteria 使用字符串键 true 和 false。"""
    return {name: {"type": "noul", "instructions": instruction, "criteria": criteria}}


def make_choice(name: str, instruction: str, criteria: dict[str, str]) -> dict:
    """构造分类问题；criteria 为 {选项名称: 选项说明}。"""
    return {name: {"type": "choice", "instructions": instruction, "criteria": criteria}}


def make_score(name: str, instruction: str, criteria: list[str]) -> dict:
    """构造评分问题；criteria 按等级排列，分数索引从 0 开始。"""
    return {name: {"type": "score", "instructions": instruction, "criteria": criteria}}
