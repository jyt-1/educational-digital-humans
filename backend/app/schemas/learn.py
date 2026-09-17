# [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— 个性化学习请求/响应模型
"""工单19 的 Pydantic 模型。响应体统一走 `ApiResponse{code,msg,data}`（文件下载接口除外）。

**历史成绩导入同时接受中文列名与英文键**：设计文档 3.2.2 把 JSON 载荷写成
`{rows:[{知识点, 得分, 满分}]}`，与 Excel 模板的列名一致——用户看到模板里是"知识点"，
代码里却必须传 `kp`，这种不一致最容易在演示时传错字段还查不出原因。
故两种都收（`AliasChoices` + `populate_by_name`）。
"""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, Field


# ------------------------------------------------------------------ 作答

class AnswerRequest(BaseModel):
    """练习作答。`user_answer` 允许为空——学生跳过也算一次作答（判错）。"""

    question_id: int
    user_answer: str | None = None


class ExamAnswerItem(BaseModel):
    question_id: int
    user_answer: str | None = None


class ExamSubmitRequest(BaseModel):
    """交卷。`answers` 可以少于试卷题数——未作答的题按错处理，不因缺项报错。"""

    plan_id: int
    answers: list[ExamAnswerItem] = Field(default_factory=list)


class VariantAnswerRequest(BaseModel):
    """变式题作答。变式题以 `questions` 行的形式落库，故同样用 `question_id` 定位。"""

    question_id: int
    user_answer: str | None = None


# ------------------------------------------------------------------ 历史成绩导入

class ScoreRow(BaseModel):
    """一行历史成绩：`知识点 / 得分 / 满分`。"""

    model_config = {"populate_by_name": True}

    kp: str = Field(validation_alias=AliasChoices("kp", "知识点", "knowledge_point"))
    score: float = Field(validation_alias=AliasChoices("score", "得分"))
    total: float = Field(validation_alias=AliasChoices("total", "满分"))


class ScoreImportRequest(BaseModel):
    """JSON 载荷导入。同一 handler 也接受 multipart 文件，两条路径复用同一校验管线。"""

    model_config = {"populate_by_name": True}

    rows: list[ScoreRow] = Field(default_factory=list)
    # 明细表内就地编辑后重提时带上批次号，按 (batch_id, student_id, kp_id) 覆盖而不新增行
    batch_id: str | None = None


# ------------------------------------------------------------------ 教师侧管理

class KpMergeRequest(BaseModel):
    """把任意 `raw_label` 改判到目标知识点：未归类归并、误挂纠正共用。"""

    raw_label: str
    target_kp_id: int


__all__ = [
    "AnswerRequest",
    "ExamAnswerItem",
    "ExamSubmitRequest",
    "KpMergeRequest",
    "ScoreImportRequest",
    "ScoreRow",
    "VariantAnswerRequest",
]
