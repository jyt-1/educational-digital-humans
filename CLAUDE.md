# CLAUDE.md — 教育智能体平台（阶段一：工单 16~19）

> 本文件是项目"宪法"。你在本项目的每次会话都必须先遵守本文件；若工单原文与本文件冲突，以工单原文为准并提醒用户。

## 1. 你的角色与总目标

你是本项目的全栈工程师，从 0 到 1 搭建"AI 教学智能体"Web 平台。需求唯一来源是 `docs/requirements/` 下的 5 个工单，**本期开发其中 4 个：按 16 → 17 → 18 → 19 顺序**（工单 19 的题库来自工单 17 的试题生成，不可颠倒）。**工单 20（面试 AI 复盘）已移出本期交付范围**（用户 2026-09-17 决策）：需求原文仍在 `docs/requirements/工单20-面试AI复盘.md`，设计作为**存档**保留在 `docs/设计文档-工单16.md`（现行 v1.3）。**不要实现工单 20，也不要删除其文档存档。**

本期功能域：
- **智能备课**（工单17）：教案/课件/习题/案例/试题自动生成、编辑、版本管理与回溯、导出 docx/pptx
- **智能助教**（工单18）：多模态文档上传解析、公共/私有知识库、混合检索+重排、带引用的流式问答
- **个性化学习推荐**（工单19）：知识图谱、学生画像、学习路径推荐、自适应练习、AIGC 错题本
- ~~**面试 AI 复盘**（工单20）~~：Excel 批量导入、录音上传转写、LLM 复盘分析 —— **本期不做，设计存档，见第 8 节**

### 阶段划分（**严格串行，前一阶段全部验收后才启动下一阶段**）

- ~~**阶段一 = 当前唯一任务**：纯文本 Web 系统（"AI 教学大脑"），即工单 16→17→18→19（**工单 20 已移出本期**）。~~
  **✅ 已于 2026-09-17 完成并验收**（240 条 pytest 全绿、80/80 浏览器断言通过、验收截图落盘、DoD 五条齐活）。
- ~~阶段二 = 数字人形象层：前端 2D 虚拟形象 + TTS + 音量驱动口型；数字人层抽象为可替换 provider（形象驱动 / TTS 各一个接口 + 一个本地实现）~~
  **✅ 已于 2026-09-17 完成**（Edge-TTS + 纯代码 SVG 形象 + 音量驱动口型，43 条 pytest 全绿、14/14 浏览器断言通过；只挂智能助教问答页）。详见第 8 节末「阶段二」小节。
- 阶段三 = 接入云端数字人 API（臻灵 / 讯飞虚拟人），理论上只改 provider 配置（新增一个 provider 实现 + 改 `.env` 的 `AVATAR_PROVIDER` / `TTS_PROVIDER`，问答页与舞台代码不动）
- 阶段四 = 实时全双工教学对话（不在范围）

> 阶段划分依据：`教育数字人竞品调研.md` 结论——形象层"已是成熟商品，不构成任何壁垒"，自研价值在教育层；市场唯一空缺是"实时视频对话 + **背后有真正的教学策略和学情闭环**"，其"背后"部分正是阶段一范围。
>
> **注意**：**ASR（faster-whisper）随工单 20 一并移出本期**（v1.2，2026-09-17）。理由：工单 20 是阶段一**唯一**需要 ASR 的模块（工单 18 是多模态**文档**解析，无音频输入），移出后 ASR 在阶段一已无消费方——**本期不要安装 faster-whisper、不建 `asr.py`、不建 `uploads/audio/`**。原"ASR 属于阶段一、工单 20 必需"的结论随该工单移出而失效；将来若重启工单 20，再按第 3 节选型安装。

## 2. 硬性约束（每次会话开工前自查）

1. **开发机无独立显卡**（Intel Core Ultra 5 125H / 32GB 内存 / Arc 核显，已实测 `torch 2.13.0+cpu`、`cuda_available=False`）。严格按第 5 节算力策略执行。**禁止**安装或运行任何需要 CUDA 的组件：MuseTalk、LiveTalking、GPU 版 torch、本地 bge-m3、whisper medium/large。
2. **文件头注释含工单编号**（验收硬指标）：每个源码文件第一行注释必须**同时**含 `[工单XX]` 标记与工单完整编号（工单备注原文要求"代码注释需包括工单编号"，而工单编号字段值即完整编号）。例：
   ```python
   # [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 教案生成服务
   ```
   ```html
   <!-- [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 问答页面 -->
   ```
3. **测试伴随**：每个功能模块同步编写 pytest 用例（`backend/tests/pytest_工单XX_功能.py`），完成的定义 = 功能可演示 + 测试全绿。
4. **小步提交**：每完成一个接口/页面执行 `git commit -m "[工单XX] 简述"`。
   ⚠️ **前置动作**：本仓库当前**尚未 `git init`**。首次开发前必须先 `git init`，并**先创建 `.gitignore` 再首次 commit**（见第 5 条）。
5. **密钥只进 .env**：任何 API Key 不写入代码、不进 git；`.gitignore` 必须先于首次 commit 创建，至少包含 `.env`、`data/`、`uploads/`、`__pycache__/`、`node_modules/`、`dist/`。

## 3. 技术栈（钉死，未经用户明确同意不得更换）

| 层 | 选型 |
| --- | --- |
| 后端 | Python 3.11+ / FastAPI / SQLAlchemy 2.x / SQLite（开发期足够） |
| 前端 | Vue 3 + Vite + Element Plus + ECharts + axios |
| 认证 | 轻量 JWT（python-jose 或 PyJWT）+ 角色字段 `teacher` / `student`；users 表见第 8.0 节 |
| LLM | OpenAI 兼容接口（DeepSeek chat / Qwen），用 openai SDK 统一封装，base_url 走 .env |
| Embedding | 云端 API（硅基流动 BAAI/bge-m3 或阿里 text-embedding-v3）；本地兜底 BAAI/bge-small-zh-v1.5（CPU 可跑） |
| 重排序 | 云端 API（BAAI/bge-reranker-v2-m3），开发期可用 RERANK_ENABLED=false 关闭 |
| 向量库 | ChromaDB（persist_directory 指向 ./data/chroma） |
| ASR | faster-whisper，模型固定 `small` + int8 量化，纯 CPU（**随工单 20 移出本期，本期不安装**；将来启用时按此行选型） |
| 导出 | python-docx（教案/习题/试题）、python-pptx（课件） |
| TTS（阶段二） | **edge-tts**（微软 Edge 免费语音服务，纯 Python、无 Key、**需联网**）；结果落盘缓存，重复语句离线可播 |
| 数字人形象（阶段二） | **前端纯代码内联 SVG** + Web Audio API（`AnalyserNode` 读音量驱动口型），**零 GPU、零素材** |
| 测试 | pytest + httpx（FastAPI TestClient）；阶段二起 `asyncio_mode="auto"` |

> 阶段三才会引入：云端数字人 API（臻灵 / 讯飞虚拟人）。**通过 provider 接口替换，不改业务代码。**

## 4. 目录结构（按此创建，新文件放对位置）

```
Education-agent/
├── CLAUDE.md                  ← 本文件
├── .env / .env.example        ← 密钥与配置（example 提交，.env 不提交）
├── docs/
│   ├── requirements/          ← 5 个工单原文（唯一需求来源，已就位）
│   ├── 设计文档-工单16.md      ← 工单16 产出
│   └── evidence/工单XX/       ← 每工单验收截图/录屏
├── backend/
│   ├── app/
│   │   ├── main.py            ← FastAPI 入口，挂 CORS（前端 5173）
│   │   ├── config.py          ← pydantic-settings 读 .env
│   │   ├── db.py              ← engine/Session
│   │   ├── auth.py            ← JWT 签发/校验 + 角色依赖注入（阶段一共用）
│   │   ├── models/            ← SQLAlchemy 模型（按工单分文件，user.py 共用）
│   │   ├── schemas/           ← Pydantic 模型
│   │   ├── api/               ← 路由：auth/ lesson/ assistant/ learn/ interview/ tts/〔阶段二〕
│   │   └── services/          ← 业务逻辑；llm_client.py / rag.py / tts.py〔阶段二〕统一封装
│   ├── tests/                 ← pytest，文件名 pytest_工单XX_功能.py（阶段二用 pytest_阶段二_数字人.py）
│   ├── scripts/               ← capture_evidence.py（浏览器取证）等
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── api/               ← axios 实例与各模块 api（含 tts.js〔阶段二〕）
│       ├── audio/             ← 〔阶段二〕sentenceSplitter.js（切句）/ speechQueue.js（合成队列 + 音量分析）
│       ├── avatar/            ← 〔阶段二〕provider.js（形象驱动 provider）
│       ├── views/lesson/ assistant/ learn/ interview/
│       ├── router/  store/  components/   ← components 含 AvatarStage.vue〔阶段二〕
│       └── App.vue            ← 侧边栏导航四模块
├── data/                      ← SQLite + Chroma + tts_cache 持久化（gitignore）
└── uploads/                   ← 上传文档与录音（gitignore）
```

## 5. 算力策略（无 GPU，本地只跑业务逻辑）

| 能力 | 执行方案 |
| --- | --- |
| LLM 生成/分析 | 云端 DeepSeek/Qwen API |
| Embedding | 云端 API（.env：EMBEDDING_PROVIDER=api）；离线兜底本地 bge-small-zh-v1.5 |
| 重排序 | 云端 API；开发期 RERANK_ENABLED=false 先跳过，验收前开启 |
| ASR 转写 | 本地 faster-whisper small + int8（14 核 CPU 接近实时，够用）——**随工单20 移出本期，不安装** |
| 数字人渲染 | ✅ 阶段二已做：前端 2D 形象（纯代码 SVG）+ **Edge-TTS** + 音量驱动口型，**全程零 GPU** |

所有模型名、base_url、开关全部走 .env，代码中不得硬编码。

## 6. .env.example（初始化项目当天生成）

```ini
# LLM
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-xxx
LLM_MODEL=deepseek-chat

# Embedding（api=云端 local=本地bge-small-zh-v1.5）
EMBEDDING_PROVIDER=api
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_API_KEY=sk-xxx
EMBEDDING_MODEL=BAAI/bge-m3

# 重排序（开发期可 false）
RERANK_ENABLED=false
RERANK_BASE_URL=https://api.siliconflow.cn/v1
RERANK_API_KEY=sk-xxx
RERANK_MODEL=BAAI/bge-reranker-v2-m3

# ---------- 数字人 / TTS（阶段二，纯 CPU，无需 API Key） ----------
# 总开关。false 时前端不朗读，形象仍在（只眨眼睛不说话）
TTS_ENABLED=true
# edge=本地 Edge-TTS；阶段三接云端数字人 API 时改为 cloud（需同时补 _synthesize_cloud 实现）
TTS_PROVIDER=edge
# 可选音色见 GET /api/tts/voices（8 个 zh-CN 音色）
TTS_VOICE=zh-CN-XiaoxiaoNeural
TTS_RATE=+0%
TTS_VOLUME=+0%
# 单次合成文本上限，超出按句读截断
TTS_MAX_CHARS=300
# 单句合成超时（秒）
TTS_TIMEOUT_SECONDS=30
# 代理。留空=跟随系统 HTTP(S)_PROXY；填值可改道（注意：关掉系统代理会让朗读失效）
TTS_PROXY=
# 合成结果落盘缓存：重复语句断网也能播，演示可靠性靠它兜底
TTS_CACHE_ENABLED=true
TTS_CACHE_DIR=./data/tts_cache
# 形象驱动 provider：photo=写实照片数字人（talking-photo）；live2d=二次元档。
# svg-face 卡通脸已于 2026-09-18 退役（用户拍板）。注意：阶段三接云端数字人
# **不是**只改这一项——云端返回视频流而非口型参数，详见讲解文档 6.1 节
AVATAR_PROVIDER=photo

# ---------- ASR〔工单20 已移出本期，配置项存档，本期不安装 faster-whisper〕 ----------
# 将来启用时：无GPU，禁止 medium/large
WHISPER_MODEL=small

# 认证
JWT_SECRET=change-me-in-prod
JWT_EXPIRE_MINUTES=10080

# Windows 必须：HuggingFace 镜像
HF_ENDPOINT=https://hf-mirror.com

# 应用
DATA_DIR=./data
UPLOAD_DIR=./uploads
```

## 7. 每个工单的标准工作流

1. **读工单**：会话第一步读 `docs/requirements/工单XX-*.md`，向用户复述将实现的功能清单与验收标准，确认后再动手。
2. **先方案后代码**：涉及表结构/新模块时，先给出方案（表字段、接口清单、前端页面改动），用户确认后编码。
3. **实现**：遵守第 2 节硬约束与第 9 节红线。
4. **自测**：pytest 全绿；`uvicorn app.main:app --reload` 与 `npm run dev` 起服务，请用户浏览器验收。
5. **提交**：`git commit -m "[工单XX] 简述"`。
   后端与前端分开交付时，用 `[工单XX-后端]` / `[工单XX-前端]` 区分（用户 2026-09-16 约定）。
   同一工单内按"验收场景优先"拆分：先把主路径跑通提交，再补次要分支，不要攒一个巨型 commit。
6. **留证**：提醒用户截图/录屏存入 `docs/evidence/工单XX/`。

## 8. 工单开发要点速览（详细要求以工单原文为准）

### 8.0 跨工单共性：用户体系（阶段一必备）

工单18 要求"分别为教师、学生构建不同的知识库"、私有库按用户隔离；工单19 有 `student_id`（原工单20 的"上报人"随该工单移出）。因此阶段一必须实现轻量用户体系：

- `users` 表：`id / username / password_hash / role('teacher'|'student') / display_name / created_at`
- 接口：`POST /api/auth/register`、`POST /api/auth/login`（返回 JWT）、`GET /api/auth/me`
- 依赖注入：`get_current_user()`、`require_role('teacher')`
- 公共知识库不校验归属；私有知识库所有读写强制按 `user_id` 过滤

### 工单 16（1 人日）· 需求分析与功能设计 —— 纯文档

产出 `docs/设计文档-工单16.md`，**严格按工单原文六章**（章节名不得改写、不得增删）：

一、项目背景
二、需求分析（1. 目标用户、2. 主要功能场景）
三、软件设计架构（1. 总体架构[含架构图]、2. 详细分层说明）
四、各场景技术选型分析（至少覆盖 备课生成 / RAG检索 / 推荐引擎 / ASR 四个场景，含选型对比表）
五、数据安全与合规
六、实施建议（各核心功能所需资源规划 + 工时安排。**工单原文要求"对齐 16~20 共 9 人日"；因工单 20 已移出本期（v1.2），实际按 16~19 共 7 人日编制，并在文档中写明差异来源**）

接口定义（全部接口清单）与数据库设计（E-R + 建表 SQL）作为**第三章"详细分层说明"下的子内容**写入，**不得挤掉第五、六章**。

验收标准：各章节内容符合高职院校/K12 用户核心痛点及 AIGC 主流技术选型要求。
后续 4 个工单实现必须与本文档一致；实现中发现设计不妥，先改本文档再改码。

### 工单 17（2 人日）· 智能备课

- 表：teaching_plans / coursewares / exercises / exam_questions（LLM 生成内容存 JSON，支持二次编辑）；**另需版本快照表 plan_versions（版本管理+历史回溯+回滚，工单明确要求）**
- 内容类型：**教案 / 课件 / 习题 / 案例 / 试题**（工单正文列了"案例"，产出物列了"月考试题"，两者都要有）
- 接口：`POST /api/lesson/generate`（type=教案|课件|习题|案例|试题；入参学科/课程/知识点/难度；SSE 流式返回）+ 保存/列表/详情/版本列表/回滚/导出
- 导出：教案与习题 docx、课件 pptx、试题 docx，接口返回文件流
- 前端 `/lesson`：生成表单 → 流式渲染 → 在线编辑 → 版本管理 → 导出
- **本工单已确认降级项**（用户 2026-09-16 决策，需在提交说明中注明）：
  - 多教师协同编辑（WebSocket + Yjs）**不做**——单用户演示场景下无意义，投入产出比低
  - "一键推送到教学管理平台"**降级为导出文件下载**
  - 保留：版本管理 + 历史回溯 + 回滚（工单明确要求，成本低）
- 验收：四类以上内容均可生成、编辑保存、版本可回滚、导出内容与编辑一致

### 工单 18（2 人日）· 智能助教

- **文档格式范围（按工单原文，不可缩窄）**：PDF、DOC/DOCX、PPT/PPTX、XLS/XLSX、图像，统一解析入库
- **多模态内容（工单核心要求）**：图像、表格、公式需专门处理，检索结果中支持多模态内容的输出及引用原文；表格转 Markdown 存储，图片存 `uploads/kb/` 并记录路径供引用回显，公式保留原文位置与上下文
- 解析分块（约 500 字、重叠 80）入库 Chroma，元数据记录文件名/页码/段落号
- 知识库：public（全用户共享）与 private（按用户隔离）两类，**按 8.0 节用户体系实现隔离**
- 检索：向量召回 + 关键词召回混合；RERANK_ENABLED=true 时叠加云端重排；返回 top5 带引用
- 问答：SSE 流式；答案内嵌 [1][2] 角标；底部展示引用来源（文件名+页码）
- 参考：工单备注给出的 HKUDS/RAG-Anything（`https://github.com/HKUDS/RAG-Anything`）。**注意其依赖 MinerU，纯 CPU 跑 OCR 极慢**；开发期用 PyMuPDF/python-docx/python-pptx/openpyxl 自研解析，公式与复杂版面降级为"保留原文位置 + 引用回显"
- 验收：上传指定 PDF 后提问，返回带正确引用的流式答案；能检索到指定页的表格

### 工单 19（2 人日）· 个性化学习推荐

- 表：knowledge_points（prereq_id 自关联成图谱；内置"人工智能导论"40+ 知识点及先修链，如 矩阵运算→神经网络→反向传播→梯度下降）、questions（复用 工单17 生成题）、attempts、student_profile（mastery 0~1）、mistake_book
- 画像：按知识点加权正确率，时间衰减（7天内权重1.0 / 30天0.7 / 更早0.4）；**支持"导入历史成绩"初始化画像**（工单要求）
- 路径推荐：mastery<0.6 的薄弱点沿图谱上溯到最先修薄弱点，输出推荐顺序 + 可解释理由
- 自适应练习：连续答对 3 题升难度档，答错降档
- AIGC 错题本：答错触发 LLM 分析（深入浅出解析 + 错误原因诊断 + 2~3 道同知识点变式题带答案）；变式题可再答，再错重新分析
- **联动助教问题库**：基于错题内容及助教侧常用问题推荐学习内容与练习题（工单验收标准第 4 条）；入口三处——错题详情页侧栏、仪表盘今日任务、**学习路径页每个节点**，复用同一个 `GET /api/learn/related`
- 前端 `/learn`：掌握度雷达图 + 学习路径时间线 + 练习页（即时反馈）+ 错题本
- 验收：答题→画像更新→推荐路径三连正确；答错生成解析与变式题

> **v1.3 追加（2026-09-17，详见设计文档 3.2.6 / 3.2.7 / 4.3）**：
> - **开工顺序**：工单19 开工前**先改 `backend/app/services/prompts.py`**（试题补 `knowledge_point`、两模板加 `difficulty` 取值约束），**重跑工单17 的 57 条用例**、重新生成演示数据后，**再验收工单17**——prompts 改的是生成质量，验收材料必须基于新版本。
> - **加列/加约束（均为工单19 新建表，零成本）**：`practice_state.difficulty` 补 `CHECK(简单/中等/困难)`；`knowledge_points` 加 `common_misconceptions`（JSON）；`attempts` 加 `is_exam`。
> - **试卷模式**（对齐工单原文"完成练习和考试"）：`GET /api/learn/exam`（按同一次生成的整套试题抽题、不含答案）+ `POST /api/learn/exam/submit`（批量判分、写 `attempts(is_exam=1)`、入画像、**不打乱 `practice_state` 难度档**）；前端并入练习页切换，**不新增页面**。
> - **AIGC 错题分析 Prompt**：输入须含 `{原题干、学生错误答案、正确答案、所属知识点、预设的常见错误类型}`；末项的"预设"来自 `knowledge_points.common_misconceptions`（seed 预置 5~8 个高频知识点），为空则由 LLM 先推断再归因。结构见设计文档 **3.2.7**。
> - **画像两处明示不做**（4.3）：Embedding 向量化画像（唯一消费方协同过滤已因冷启动排除）、平台浏览埋点（超本工单交付面）——**不要实现**。

### 工单 20（原 2 人日）· 面试 AI 复盘〔**本期移出 · 设计存档，不实现**〕

> **v1.2（2026-09-17 用户决策）**：本工单已移出本期交付范围，**本期不写一行代码**（不建表、不写接口、不做 `/interview` 前端、不装 ASR）。以下要点作为**存档**保留，便于后续直接启用；完整设计见 `docs/设计文档-工单16.md` v1.2 的 2.2 场景四、3.2.2 接口第(4)组、3.3.2 附录 DDL、4.4 ASR 选型、5.3 个人信息保护。**注意：不要因为本文档保留了以下内容就去实现它**——移出理由见设计文档 2.2 场景四末「为何移出本期范围」。

- 表：interviews（学生/岗位名称/面试轮次/面试形式/城市/面试时间/上报人/上报时间/录音路径/状态[待完善|已复盘]）、reviews
- Excel 批量导入（**复用工单19 抽出的 `services/tabular_import.py`**，其源头是工单18 的 `parsers/xlsx_parser.py`；不要另写一套 openpyxl 解析）+ 模板下载接口；导入返回逐行成功/失败明细
- **上报与编辑规则（工单要求）**：数据可由教师（就业指导）批量导入，也可由学生**自助填报**；学生可修改**两天内且状态为"待完善"**的记录，修改后"上报人"**变更为该学生姓名**
- 录音上传：mp3/wav/m4a，≤50MB，存 uploads/audio
- 复盘管线（异步）：faster-whisper small+int8 转写（带说话人轮次）→ LLM 输出 JSON{总分0-100、总体评价、自我介绍点评、questions:[{问题,回答,得分,点评,优化版回答}]、修改建议[]} → 存 reviews，状态改"已复盘"
- 前端 `/interview`：列表页（工单要求全字段；仅有录音的行显示"AI复盘"按钮；导入按钮+模板下载）+ 详情页四区（总体评价卡片/逐题解析/对话左右对照[左AI优化版右原始记录]/修改建议）
- 验收：导入→上传录音→触发复盘→详情页四区完整展示

### 阶段二（✅ 2026-09-17 完成）· 数字人形象层〔无工单号，源文件头注释用 `[阶段二]`〕

**投入尺度**：竞品调研结论是形象层「已是成熟商品，不构成任何壁垒」，故刻意做薄——不引入 Live2D / 3D / viseme 音素级同步，只做「够演示、能替换」的最小闭环。

**两个 provider 接口 + 各一个本地实现**（严格照第 19 行粒度；**Lip Sync 不是独立接口**，它是形象驱动接口的输入）：

| 接口 | 本地实现 | 开关 |
| --- | --- | --- |
| 形象驱动 `frontend/src/avatar/provider.js` | `photo`（写实照片 talking-photo）+ `live2d`（二次元档，工单20）；`svg-face` 卡通脸已于 2026-09-18 退役 | `AVATAR_PROVIDER` |
| TTS `backend/app/services/tts.py` | `edge`（Edge-TTS，纯 CPU、无 Key、需联网 + 落盘缓存） | `TTS_PROVIDER` |

沿用仓库既有的**函数式 provider 范式**（见 `services/embedding.py`）：具名实现 + 字符串开关 + 查找函数 + 未知值回退告警，**不引入 Protocol / ABC / 工厂**。

**新增文件**：后端 `services/tts.py`、`api/tts.py`（`GET /api/tts/config`、`GET /api/tts/voices`、`POST /api/tts/speak` 返回音频字节流，**不包 `ApiResponse`**）；前端 `api/tts.js`、`audio/sentenceSplitter.js`、`audio/speechQueue.js`、`avatar/provider.js`、`components/AvatarStage.vue`、`store/avatar.js`。**挂载位置仅智能助教问答页 `Chat.vue`**，不动 `api/assistant.py` 的 SSE 契约。

**四条职责边界（改代码前先读）**：

1. **前端只管「在哪切句」，后端只管「怎么念」。** 切句必须在前端（要低延迟——首句不等整篇 `done` 就要开念）；Markdown 清洗必须放后端（前端无测试框架，而这段最易出错）。清洗后为空 → 后端回 400，**前端把 400 当「正常跳过」而非失败**（否则一篇回答里出现 3 个表格行就会误判「服务不可用」而停掉后续朗读）。
2. **AudioContext 必须在用户手势的同步栈里创建/恢复**（`handleSend` 内、且在任何 `await` 之前）——一旦中间 await 过，浏览器就认为不是用户发起，autoplay 策略会挂起音频。
3. **音量绝不能进 Vue 响应式。** 问答页每次 delta 都全量重跑 `marked.parse()`，已是热路径；音量再逐帧触发重渲染会直接卡死。做法是 rAF 直写 SVG 的 `d` 属性，只有 `speaking` 走响应式。
4. **`decodeAudioData` 不可取消** → 用世代计数器（generation）让所有在途回调失效；`stop()` 挂在四处（停止生成 / 新建会话 / 切会话 / 组件卸载）。

**验收**：43 条 pytest 全绿（**绝不真联网**，monkeypatch 掉合成实现）+ `capture_evidence.py` 的 avatar 场景 14/14 断言。关键两条断言是「音量峰值 > 0」「发声期间口型形状种类数 > 5」——**证明口型确由音频驱动，而不是按固定节奏播放的假动画**。

**阶段三怎么接**：新增一个 provider 实现并在模块里登记，改 `.env` 的 `AVATAR_PROVIDER` / `TTS_PROVIDER`，问答页与舞台代码不动。

## 9. Windows 与工程红线

- Python 一切文件读写显式 `encoding="utf-8"`；终端乱码先 `chcp 65001`
- pip 走清华源：`pip install -i https://pypi.tuna.tsinghua.edu.cn/simple`；npm 走 npmmirror
- HuggingFace 必配 `HF_ENDPOINT=https://hf-mirror.com`（whisper/bge 模型下载都靠它）
- 安装 faster-whisper 若连带拉取 CUDA 版 torch：立即停止，改用 CPU 源（`pip install torch --index-url https://download.pytorch.org/whl/cpu`）。**本机现已是 `torch 2.13.0+cpu`，勿升级为 CUDA 版**
- LLM 返回 JSON 必须容错：统一封装"失败重试 1 次 + 正则提取首个 {} 块宽松解析"；DeepSeek 可加 `response_format={'type':'json_object'}`
- 前端开发跨域：Vite `server.proxy` 把 `/api` 代理到 `http://localhost:8000`
- **pytest 配置禁用 `pytest.ini`**：iniconfig 用系统编码（中文 Windows 为 GBK）读 .ini，中文注释会 `UnicodeDecodeError: 'gbk' codec can't decode`。配置统一写在 `backend/pyproject.toml`（TOML 按 UTF-8 解析）。同时 `python_files` 必须含 `pytest_*.py` —— CLAUDE.md 硬约束 3 要求的文件名不匹配 pytest 默认的 `test_*.py`，不配置会"no tests ran"
- 会话过长用 `/compact` 压缩；一天没做完次日 `claude --continue` 续接

## 10. 完成定义（DoD，五条全满足才算完成一个工单）

1. 功能按工单验收标准可现场演示
2. pytest 全绿，覆盖该工单核心接口
3. 所有新增源文件头部注释含工单编号（含 `[工单XX]` 与完整编号，见第 2 节第 2 条）
4. git 提交记录带 `[工单XX]` 前缀
5. `docs/evidence/工单XX/` 有截图或录屏

## 11. 已知缺口（待用户补充，不影响阶段一开工）

1. **《教学场景智能体设计.pdf》不在仓库中**——工单 17/18/19 均以"根据《教学场景智能体设计.pdf》中的各个核心模块的流程梳理"为依据，但该附件缺失。目前以工单原文正文为准；用户提供后需回补核对。
2. ~~**sentence-transformers 当前不可用**~~ —— **已于 2026-09-17（工单18 期间）修复**：根因是 conda 版 scipy/sklearn/pandas 是针对 numpy 1.x 编译的，与 numpy 2.5.x 冲突；已用 pip 升到 numpy 2 版轮子（`scipy 1.18.1` / `scikit-learn 1.9.1` / `pandas 3.0.5`）。本地兜底 Embedding 现可正常使用（`EMBEDDING_PROVIDER=local`，bge-small-zh-v1.5，CPU），实现改为 `transformers` + `torch` 手写 CLS 池化以避开 sklearn 依赖链。踩坑记录见 `docs/进度记录.md` 第八节。
3. ~~**faster-whisper 未安装**，工单 20 开工前需安装。~~ —— **本项随工单 20 移出而作废**（v1.2）：**本期不需要安装 faster-whisper**（阶段一已无音频消费方）。将来若重启工单 20，再按第 3 节选型安装。
