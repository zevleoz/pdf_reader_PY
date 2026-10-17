# 部署 Runbook（2.0 上线 / 迁移 / 回滚）

> 环境变量字段说明见 [deployment_env.md](deployment_env.md)。
> 本地路径：`data/y4_students.db`；生产路径：`/opt/y4_report/data/y4_students.db`。

## 迁移总流程（先备份，再迁移，可回滚）

```bash
# 0) 停机（生产）
sudo systemctl stop y4_report

# 1) 备份 SQLite（并记录备份文件名）
TS=$(date +%Y%m%d_%H%M%S)
cp /opt/y4_report/data/y4_students.db /opt/y4_report/data/y4_students.db.bak_$TS
cp /opt/y4_report/.env.production /root/.env.production.bak_$TS   # 备份到 root 家目录，不进仓库

# 2) A 包迁移：users 表 + 初始 admin + students.student_code 回填（幂等）
cd /opt/y4_report && sudo -u y4report venv/bin/python scripts/migrate_2_0_foundation.py
#    预期输出：users 表创建、初始 admin 创建（用户名/密码读 Y4_INITIAL_ADMIN_USER /
#    Y4_INITIAL_ADMIN_PASSWORD，绝不硬编码）、现有学生按 id 升序补发 Y4-0001…
#    users 非空时自动跳过初始 admin 创建，重复执行安全。

# 3) C 包迁移：问卷 6+1 张新表 + questionnaires_seed/ 题库 upsert（幂等）
sudo -u y4report venv/bin/python scripts/migrate_2_0_questionnaires.py
#    预期输出：6 份题库导入、规则版本 upsert（published 1 个），重复执行安全。

# 4) 迁移后只读校验
sudo -u y4report venv/bin/python - <<'EOF'
import sqlite3
c = sqlite3.connect('/opt/y4_report/data/y4_students.db')
print('users:', c.execute('select count(*) from users').fetchone())
print('student_code 空值:', c.execute("select count(*) from students where student_code is null or student_code=''").fetchone())
print('questionnaires:', c.execute('select count(*) from questionnaires').fetchone())
print('rules published:', c.execute("select count(*) from questionnaire_rules where status='published'").fetchone())
EOF
#    期望：users ≥ 1；student_code 空值 = 0；questionnaires = 6；rules published = 1

# 5) 起服务 + 回归
sudo systemctl start y4_report && systemctl is-active y4_report
```

迁移脚本入口汇总：
- A 包：`scripts/migrate_2_0_foundation.py`（建 users 表、初始 admin、student_code 回填）
- C 包：`scripts/migrate_2_0_questionnaires.py`（问卷 7 张表、questionnaires_seed/ 题库 upsert）

## 回滚步骤（任何一步失败时）

```bash
sudo systemctl stop y4_report
cp /opt/y4_report/data/y4_students.db.bak_$TS /opt/y4_report/data/y4_students.db
git checkout <迁移前的 commit>        # 或按 HANDOFF 的 .bak 文件恢复 app.py 等
find /opt/y4_report -name __pycache__ -type d -prune -exec rm -rf {} +
sudo systemctl start y4_report
```

回滚后旧代码可正常服务（回滚演练已验证：恢复备份 → `/login` 200）。

## 部署/重启顺序（生产，`/opt/y4_report`）

```bash
# 1) 上线代码
cd /opt/y4_report && sudo -u y4report git pull        # 或按既定发布方式
sudo -u y4report venv/bin/pip install -r requirements.txt   # A–E 应零新增依赖
# 2) 更新 env（如有新变量），注意 600 权限与属主
sudo nano /opt/y4_report/.env.production && sudo chmod 600 /opt/y4_report/.env.production
# 3) 清字节码缓存（避免旧 .pyc 干扰）
sudo find /opt/y4_report -name __pycache__ -type d -prune -exec rm -rf {} +
# 4) 迁移（上面「迁移总流程」第 2–4 步：stop → 备份 → 迁移 → 校验）
# 5) 重启（env 变更必须 restart，不是 reload——systemd 仅在启动时读 EnvironmentFile）
sudo systemctl restart y4_report && systemctl is-active y4_report
sudo nginx -t && sudo systemctl reload nginx           # 仅在 nginx 配置有变时；本期不应有变
# 6) 回归（部署后一轮）
```

CF Tunnel 侧无需操作（隧道配置不变）；部署后用隧道域名验证 524 不复发。
注意：`DATABASE_URL` 若非缺省 SQLite，迁移前先确认实际值（PostgreSQL 走
`Base.metadata.create_all` 建新表，回填脚本对非 SQLite 后端会跳过 student_code 回填）。
