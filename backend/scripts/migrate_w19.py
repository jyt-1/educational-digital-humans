# [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— 增量迁移 CLI
"""工单19 增量结构迁移的**命令行入口**（幂等，可重复执行）。

迁移逻辑在 `app/migrations.py`——因为 `app.db.init_db()` 也会调用它，
启动服务或跑 pytest 时已自动执行，本文件只是让你能单独跑一次看改动清单：

    cd backend && python -m scripts.migrate_w19

（把逻辑放 `app/` 而非本文件，是为了不让 `app` 反向依赖 `scripts`。）
"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许 `python scripts/migrate_w19.py` 这种从 backend/ 直接执行的写法
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.migrations import run  # noqa: E402


def main() -> None:
    changes = run()
    print("工单19 迁移完成：")
    for line in changes:
        print(f"  - {line}")
    if len(changes) == 1:
        print("  （结构已是最新，无需改动）")


if __name__ == "__main__":
    main()
