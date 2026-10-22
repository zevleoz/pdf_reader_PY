"""Growth Talk 业务错误。"""
from __future__ import annotations


class ActionError(Exception):
    """审核动作的业务错误，携带 HTTP 状态码供蓝图映射。"""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message
