"""问卷识别规则引擎包（Agent C）。

纯规则求值，不导入 Flask、不访问数据库；规则版本解析与落库在
``questionnaire_store.py``（集成胶水层）。
"""
from __future__ import annotations

from .engine import (OPS, eval_condition, eval_when, evaluate, norm_code,
                     validate_rules)
from .schema import (TYPES, group_by_section, questions_of, sections_of,
                     validate_answers)

__all__ = ["OPS", "eval_condition", "eval_when", "evaluate", "norm_code",
           "validate_rules", "TYPES", "group_by_section", "questions_of",
           "sections_of", "validate_answers"]
