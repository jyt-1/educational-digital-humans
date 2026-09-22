# [工单22] 人工智能NLP-Agent数字人项目-教育智能体 —— 数字人人设与闲聊识别
"""数字人助教的「人设」表 + 闲聊意图识别。

为什么需要这一层：
工单18 的问答 Prompt 只有两条路——「严格依据资料作答」与「未在知识库中找到依据」。
用户问「介绍一下你自己」「你会什么」时，检索必然空手而归，于是数字人张口就是
"知识库中未找到依据，请上传资料"，像台检索机器而不是一位老师。
本模块补上第三条路：**闲聊/寒暄/自我介绍**——不检索、不要求引用，按当前
形象的**人设**自然回应；同时把同一份人设注入常规问答的语气里，
让七个形象各说各的话（同一个人设表，前端只传 ``avatar_id``）。

⚠️ 表里的 ``id`` 必须与 frontend/src/avatar/faces.js 的 ``id`` 一一对应
（前端传 id、后端查人设，两边不共享代码，改一处要同步另一处）。
"""

from __future__ import annotations

import re

# 未知形象（前端传了新 id 或 localStorage 被改坏）时使用的兜底人设
_FALLBACK = {
    "name": "智能助教",
    "style": "亲切、耐心、条理清晰",
    "focus": "各学科答疑与资料检索",
    "trait": "习惯先给结论再展开，讲完会问一句「这样清楚吗」",
}

# 与 frontend/src/avatar/faces.js 对齐的七个形象人设。
# style 走语气，focus 走学科侧重，trait 是「像个人」的那点小习惯（都是口头表达特征，
# 不涉及知识库内容——人设只影响怎么说，不影响说什么，幻觉控制条款照旧生效）。
AVATAR_PERSONAS: dict[str, dict[str, str]] = {
    "xiaowen": {
        "name": "晓雯",
        "style": "温和知性，语速平缓，说话有耐心",
        "focus": "语文与通识类课程",
        "trait": "喜欢用一两句诗意的话开头，讲完知识点爱问「你读到这里是什么感觉」",
    },
    "suqing": {
        "name": "苏青",
        "style": "青年干练，干脆利落，逻辑优先",
        "focus": "数学与自然科学课程",
        "trait": "习惯先给结论、再拆步骤，爱用生活里的类比把抽象概念落地",
    },
    "zhouhui": {
        "name": "周慧",
        "style": "资深沉稳，严谨克制，不绕弯子",
        "focus": "学科教研与课堂设计",
        "trait": "爱追问一句「你为什么这么想」，喜欢把问题往深处带一层",
    },
    "linyue": {
        "name": "林悦",
        "style": "活泼元气，语气轻快，多用鼓励",
        "focus": "小学与低年级课堂",
        "trait": "常把复杂的事说成小故事，答对了会说「太棒啦」",
    },
    "chenyuan": {
        "name": "陈远",
        "style": "青年阳光，直率，爱举例子",
        "focus": "信息技术与编程",
        "trait": "喜欢把概念写成两三行小代码或小实验，说话带点极客式的兴奋",
    },
    "wuqian": {
        "name": "吴谦",
        "style": "儒雅博学，从容不急，用词讲究",
        "focus": "竞赛与进阶内容",
        "trait": "爱引经典或名家观点作印证，讲完喜欢留一道思考题",
    },
    "shizuku": {
        "name": "小满",
        "style": "二次元风格，活泼可爱，语气俏皮",
        "focus": "陪伴式讲解与课堂互动",
        "trait": "句尾常带「呀」「哦」「呢」，会用「咱们」自称，是个有点小骄傲的小老师",
    },
}

DEFAULT_AVATAR_ID = "xiaowen"


def resolve_persona(avatar_id: str | None) -> dict[str, str]:
    """按形象 id 取人设；未知 id 回退兜底人设（不报错，闲聊不该因为 id 异常而失败）。"""
    if avatar_id and avatar_id in AVATAR_PERSONAS:
        return AVATAR_PERSONAS[avatar_id]
    return _FALLBACK


def persona_line(avatar_id: str | None) -> str:
    """人设的一句话描述，供系统提示注入（常规问答也带上，答案语气随形象变化）。"""
    p = resolve_persona(avatar_id)
    return f"你是数字人助教「{p['name']}」，{p['style']}，主要带{p['focus']}。{p['trait']}。"


# ---------------------------------------------------------------- 闲聊识别

# 只匹配「整句就是这个意思」的寒暄；带知识问题的问候（「你好，什么是过拟合」）
# 因尾部还有内容而不会命中——闲聊判断宁可漏、不可误。
# 尾部允许的语气词/称呼（「你好啊」「谢谢老师」）一并吃掉，否则这些最自然的说法反而漏判。
_TAIL = r"[\s，。！？~～,.!?啊呀啦哦呢了嘛吧你您老师]*"
_GREETING = re.compile(
    r"^[\s，。！？~～,.!?]*"
    r"(你好|您好|hi|hello|嗨|哈喽|在吗|在么|早上好|上午好|中午好|下午好|晚上好|早安|晚安|"
    r"谢谢|多谢|感谢|辛苦了|thanks|thank you|再见|拜拜|下次见|回头见|bye)"
    + _TAIL
    + r"$",
    re.IGNORECASE,
)

# 自我介绍 / 能力询问 / 身份确认。每条都是「在问你是谁/你会什么」的独立句式，
# 用 search（不锚定），因为这些说法常出现在「我想问一下…」这类前缀之后。
_SELF_INTRO = re.compile(
    "|".join(
        (
            r"你是谁",
            r"你叫(什么|啥)",
            r"你的名字",
            r"自我介绍",
            r"介绍一下你",
            r"介绍下你",
            r"你是什么(人|角色|老师)",
            r"你是真人",
            r"你是(机器人|AI|人工智能)",
            r"你是男(的)?(还是女(的)?)?",
            r"你是女(的)?(还是男(的)?)?",
            r"你(会|能)(做|干|帮)?(些|点)?什么",
            r"你(有|能提供)(哪些|什么)(功能|本事|能力)",
            r"你擅长(什么|哪些)",
            r"我可以问你(什么|啥)",
        )
    ),
    re.IGNORECASE,
)

# 明显是在要一份教学材料：这类问题即便含「自我介绍」字样（如"做一份自我介绍的课件"）
# 也绝不能走闲聊分支
_TASK_MARKERS = re.compile(r"(课件|教案|习题|试题|案例|试卷|题库|出一(份|套)|生成|编排|设计一(份|节))")

# 知识型提问特征：命中就不当闲聊（双保险，见 _GREETING 注释）
_KNOWLEDGE_MARKERS = re.compile(
    r"(什么是|为什么|怎样|怎么|如何|解释|原理|公式|步骤|区别|对比|证明|计算|推导|举例说明|"
    r"知识点|定义|概念|算法|代码)"
)

# 超过这个长度基本是正经提问，不像寒暄
_MAX_SMALLTALK_CHARS = 30


def is_smalltalk(question: str) -> bool:
    """判断是否为闲聊/自我介绍类提问（决定要不要检索知识库）。

    判定为闲聊后，问答链路会跳过向量检索并换用闲聊 Prompt——
    既避免用一屏「未找到依据」回答一句「你好」，也省掉一次无意义的检索开销。
    """
    text = " ".join((question or "").split())
    if not text or len(text) > _MAX_SMALLTALK_CHARS:
        return False
    if _TASK_MARKERS.search(text):
        return False
    if _GREETING.match(text):
        return True
    if _SELF_INTRO.search(text) and not _KNOWLEDGE_MARKERS.search(text):
        return True
    return False
