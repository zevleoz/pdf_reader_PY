"""E4 映射 seed（Y4 编号 → E4 维度/子类）。

来源：本地 prompt lab 人工指认导出。由 seed_e4_mapping.py 幂等导入，
不要手改结构；在 prompt lab 调整后重新导出即可。
"""

SEED_ENTRIES = [
    {"code": "001", "e4_dims": [
        {"e4_dim": "E3", "e4_sub": "大脑引擎"},
    ]},
    {"code": "002", "e4_dims": [
        {"e4_dim": "E3", "e4_sub": "大脑引擎"},
    ]},
    {"code": "003", "e4_dims": [
        {"e4_dim": "E3", "e4_sub": "大脑引擎"},
    ]},
    {"code": "004", "e4_dims": [
        {"e4_dim": "E3", "e4_sub": "大脑引擎"},
    ]},
    {"code": "005", "e4_dims": [
        {"e4_dim": "E3", "e4_sub": "大脑引擎"},
        {"e4_dim": "E4", "e4_sub": ""},
    ]},
    {"code": "006", "e4_dims": [
        {"e4_dim": "E3", "e4_sub": "大脑引擎"},
        {"e4_dim": "E4", "e4_sub": ""},
    ]},
    {"code": "007", "e4_dims": [
        {"e4_dim": "E3", "e4_sub": "大脑引擎"},
        {"e4_dim": "E4", "e4_sub": ""},
    ]},
    {"code": "008", "e4_dims": [
        {"e4_dim": "E3", "e4_sub": "大脑引擎"},
    ]},
    {"code": "009", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": "焦虑状态"},
        {"e4_dim": "E3", "e4_sub": ""},
    ]},
    {"code": "011", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "012", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "013", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "014", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "015", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
        {"e4_dim": "E3", "e4_sub": "动力引擎"},
    ]},
    {"code": "016", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
        {"e4_dim": "E3", "e4_sub": "动力引擎"},
    ]},
    {"code": "017", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
        {"e4_dim": "E4", "e4_sub": ""},
    ]},
    {"code": "018", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
        {"e4_dim": "E3", "e4_sub": "动力引擎"},
    ]},
    {"code": "019", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "020", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "021", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "022", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "023", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "024", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "025", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "026", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "027", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "028", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "029", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "030", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "031", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "045", "e4_dims": [
        {"e4_dim": "E2", "e4_sub": "饮食"},
    ]},
    {"code": "046", "e4_dims": [
        {"e4_dim": "E2", "e4_sub": ""},
    ]},
    {"code": "047", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": "焦虑状态"},
        {"e4_dim": "E2", "e4_sub": "睡眠"},
    ]},
    {"code": "048", "e4_dims": [
        {"e4_dim": "E2", "e4_sub": ""},
    ]},
    {"code": "049", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": "焦虑状态"},
        {"e4_dim": "E2", "e4_sub": ""},
    ]},
    {"code": "050a", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
        {"e4_dim": "E2", "e4_sub": ""},
    ]},
    {"code": "050", "e4_dims": [
        {"e4_dim": "E2", "e4_sub": ""},
    ]},
    {"code": "051", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "054", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "056", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "057", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "058", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "059", "e4_dims": [
        {"e4_dim": "E3", "e4_sub": ""},
    ]},
    {"code": "060", "e4_dims": [
        {"e4_dim": "E3", "e4_sub": "动力引擎"},
        {"e4_dim": "E4", "e4_sub": ""},
    ]},
    {"code": "061", "e4_dims": [
        {"e4_dim": "E3", "e4_sub": "动力引擎"},
    ]},
    {"code": "062", "e4_dims": [
        {"e4_dim": "E3", "e4_sub": "动力引擎"},
    ]},
    {"code": "063", "e4_dims": [
        {"e4_dim": "E3", "e4_sub": "大脑引擎"},
    ]},
    {"code": "064", "e4_dims": [
        {"e4_dim": "E3", "e4_sub": "大脑引擎"},
        {"e4_dim": "E4", "e4_sub": ""},
    ]},
    {"code": "065", "e4_dims": [
        {"e4_dim": "E3", "e4_sub": "大脑引擎"},
        {"e4_dim": "E4", "e4_sub": ""},
    ]},
    {"code": "066", "e4_dims": [
        {"e4_dim": "E3", "e4_sub": "动力引擎"},
    ]},
    {"code": "067", "e4_dims": [
        {"e4_dim": "E3", "e4_sub": "动力引擎"},
    ]},
    {"code": "068", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": "学习信心"},
        {"e4_dim": "E3", "e4_sub": "动力引擎"},
    ]},
    {"code": "069", "e4_dims": [
        {"e4_dim": "E4", "e4_sub": ""},
    ]},
    {"code": "070", "e4_dims": [
        {"e4_dim": "E4", "e4_sub": ""},
    ]},
    {"code": "071", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "078", "e4_dims": [
        {"e4_dim": "E1", "e4_sub": ""},
    ]},
    {"code": "080", "e4_dims": [
        {"e4_dim": "E4", "e4_sub": ""},
    ]},
    {"code": "082", "e4_dims": [
        {"e4_dim": "E4", "e4_sub": ""},
    ]},
    {"code": "085", "e4_dims": [
        {"e4_dim": "E4", "e4_sub": ""},
    ]},
    {"code": "128", "e4_dims": [
        {"e4_dim": "E3", "e4_sub": "动力引擎"},
    ]},
    {"code": "129", "e4_dims": [
        {"e4_dim": "E3", "e4_sub": "动力引擎"},
    ]},
    {"code": "130", "e4_dims": [
        {"e4_dim": "E3", "e4_sub": "动力引擎"},
    ]},
]
