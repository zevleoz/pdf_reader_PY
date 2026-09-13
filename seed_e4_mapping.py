"""把 e4_mapping_seed.SEED_ENTRIES 幂等写入当前配置的数据库。

用法（服务器）：
    cd /opt/y4_report
    venv/bin/python seed_e4_mapping.py

只 upsert seed 中的 code，不影响学生/报告等其他数据，可重复执行。
"""

from e4_mapping_seed import SEED_ENTRIES
import db


def main() -> None:
    db.init_db()
    db.save_e4_mapping(SEED_ENTRIES)
    mapping = db.get_e4_mapping()
    print(f"seed 完成：{len(SEED_ENTRIES)} 个 code，库内现有 {len(mapping)} 个 code 的映射")


if __name__ == "__main__":
    main()
