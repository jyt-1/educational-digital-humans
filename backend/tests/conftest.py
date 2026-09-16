# [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— pytest 公共夹具
"""测试夹具：独立临时数据库 + TestClient + 师生账号。

必须在导入 app 之前设置环境变量，因为 settings 是模块级单例、engine 在导入时创建。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# 保证 backend/ 在 sys.path 中，使 `import app...` 可用
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# ---- 隔离测试环境：临时数据目录，绝不污染真实的 data/ ----
_TMP_DIR = tempfile.mkdtemp(prefix="eduagent_test_")
os.environ["DATA_DIR"] = _TMP_DIR
os.environ["UPLOAD_DIR"] = os.path.join(_TMP_DIR, "uploads")
# 密钥长度需 >= 32 字节，否则 PyJWT 会发出 InsecureKeyLengthWarning
os.environ["JWT_SECRET"] = "test-secret-key-for-pytest-only-0123456789"
os.environ["LLM_API_KEY"] = ""  # 默认未配置，需要时由测试自行 mock

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    # 使用 with 触发 lifespan，完成建表
    with TestClient(app) as c:
        yield c


def _register_and_login(client: TestClient, username: str, role: str) -> str:
    client.post(
        "/api/auth/register",
        json={"username": username, "password": "pwd123456", "role": role,
              "display_name": username},
    )
    resp = client.post(
        "/api/auth/login", json={"username": username, "password": "pwd123456"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


@pytest.fixture(scope="session")
def teacher_token(client: TestClient) -> str:
    return _register_and_login(client, "teacher_zhang", "teacher")


@pytest.fixture(scope="session")
def student_token(client: TestClient) -> str:
    return _register_and_login(client, "student_li", "student")


@pytest.fixture(scope="session")
def other_teacher_token(client: TestClient) -> str:
    """第二个教师账号，用于验证越权隔离。"""
    return _register_and_login(client, "teacher_wang", "teacher")


@pytest.fixture(scope="session")
def auth():
    """把裸 token 包成 Authorization 头。"""

    def _auth(token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    return _auth
