# 教育数字人项目 · 从 0 到 1 实施指南（Claude Code 版）

> 适用环境：Windows 11 + Git Bash · 参照工单：16～20 号（共 9 人日）
> 目标：用 Claude Code 智能编程工具，按工单顺序在本地电脑上完成"教育智能体"全部功能开发

---

## 0. 项目全貌：5 个工单在做什么

| 工单 | 模块 | 核心产出 | 工时 | 依赖 |
| --- | --- | --- | --- | --- |
| 16【必选】 | 需求分析与功能设计 | 《教育智能体需求分析与软件架构设计》文档（六章结构） | 1 人日 | 无 |
| 17 | 智能备课 | 输入课程信息 → AI 生成教案/课件/习题/月考试题，在线编辑、检索引用、导出 Word/PPT、版本管理 | 2 人日 | 工单16 |
| 18 | 智能助教 | 多模态 RAG：公共+私有知识库、混合检索+重排、带引用与富媒体回答 | 2 人日 | 工单16 |
| 19 | 个性化学习推荐 | 学生画像、知识图谱路径推荐、自适应练习、AIGC 错题本 | 2 人日 | 工单17（用其试题） |
| 20 | 面试 AI 复盘 | 面试列表+Excel 批量导入、录音转写、AI 打分点评/优化回答/总体评价 | 2 人日 | 工单16 |

**开发顺序固定为：16 → 17 → 18 → 19 → 20**（19 要用 17 生成的题库初始化画像，20 独立）。

**统一技术栈（务必先定死，再让 Claude 开工）：**

| 层 | 选型 | 理由 |
| --- | --- | --- |
| 后端 | Python 3.12 + FastAPI + SQLAlchemy + SQLite | 单文件零配置，验收演示够用 |
| 前端 | Vue 3 + Vite + Element Plus + ECharts + Axios | 国内生态成熟，Claude 熟练 |
| 大模型 | DeepSeek 或 通义千问（OpenAI 兼容接口） | 国内直连、便宜、换模型只改 base_url |
| Embedding | 本地 `BAAI/bge-m3`（sentence-transformers）或阿里 text-embedding-v3 | 中文效果好 |
| 重排序 | `BAAI/bge-reranker-v2-m3` | 工单18要求 |
| 向量库 | ChromaDB | pip 一装即用，生产可换 Milvus |
| ASR 语音识别 | faster-whisper（本地） | 工单20录音转写，免费离线 |
| 文档解析 | PyMuPDF / python-docx / python-pptx / openpyxl | 工单18多格式+工单20 Excel导入 |
| 导出 | python-docx / python-pptx | 工单17多格式导出 |

**无独立显卡（核显）电脑适配说明：**

若开发机为 Intel 核显、无 N 卡（如 Core Ultra 5 125H + Arc 核显 + 32GB），技术栈按以下方式调整，原则是"本地只跑业务逻辑，AI 重活走云端 API"：

- **Embedding**：改用云端 API（硅基流动 SiliconFlow 的 BAAI/bge-m3 有免费额度，或阿里 text-embedding-v3），`.env` 中配 `EMBEDDING_PROVIDER=api`；本地兜底方案换小模型 `bge-small-zh-v1.5`（CPU 上够快）
- **重排序 bge-reranker-v2-m3**：改走云端 API（硅基流动有同款模型），开发期可先关闭重排环节，验收前再开启
- **ASR**：faster-whisper 用 `small` 模型 + int8 量化，这颗 14 核 U 纯 CPU 转写接近实时，够用；追求稳妥可用云端 ASR（阿里 paraformer）兜底
- **LLM / TTS / 数字人渲染**：本就走云端，不受影响
- **唯一不能本地做的**：实时神经渲染数字人（MuseTalk/LiveTalking 需要 N 卡 CUDA）。替代：① 云端数字人 API 渲染后视频流回传；② 浏览器 2D 虚拟形象 + TTS 音素/音量驱动口型（零 GPU，演示效果尚可）

---

## 1. 阶段一：环境准备（Day 0，约半天）

### 1.1 安装基础软件

1. **Node.js 22 LTS**（Claude Code 与前端 Vite 都需要）：官网 https://nodejs.org 下载安装，验证：
   ```bash
   node -v   # v22.x
   npm -v
   ```
2. **Python 3.12+**：你电脑已装（3.12.7 / 3.13.12 均可），验证 `python --version`。
3. **Git**：https://git-scm.com，安装时默认勾选 Git Bash。
4. **终端**：Claude Code 在 Windows 上推荐在 **Git Bash** 中运行（兼容性最好）。

### 1.2 安装 Claude Code

在 Git Bash 中二选一：

```bash
# 方式A：npm 全局安装（最常用）
npm install -g @anthropic-ai/claude-code

# 方式B：Windows 原生安装器（PowerShell 中执行）
# irm https://claude.ai/install.ps1 | iex
```

安装完成后，cd 到任意目录执行 `claude`，首次会引导登录（Claude Pro/Max 订阅 OAuth，或配置 `ANTHROPIC_API_KEY`）。

### 1.3 账号与网络的现实情况（重要）

- Anthropic 官方目前**不向中国大陆地区提供注册与 API 服务**。可选路径：
  - **路径A**：持有合规的 Claude Pro/Max 订阅账号 + 合规网络环境，直接 OAuth 登录。
  - **路径B**：已有海外申请的 API Key，通过设置环境变量使用（必要时配合中转 `ANTHROPIC_BASE_URL`，具体地址自备并注意安全）。
  - **路径C（兜底）**：若 Claude Code 确实不可用，工单备注明确允许"使用 Cursor、Trae 等智能编程工具"——本指南的 CLAUDE.md 与提示词模板同样适用于 Cursor（Project Rules）/ Trae（Rules）。
- 无论走哪条路径，**项目代码本身用的大模型（DeepSeek/Qwen）是国内直连的，不受影响**。

### 1.4 项目大模型 Key 申请（与编程工具分开）

1. DeepSeek：https://platform.deepseek.com 注册 → 充值 10 元 → 创建 API Key（足够全部开发测试）。
2. 或通义千问：https://dashscope.console.aliyun.com → 开通 → 获取 sk- 开头 Key（新用户有免费额度）。

---

## 2. 阶段二：项目初始化（Day 0.5）

### 2.1 建目录、拷工单、初始化 Git

```bash
mkdir edu-agent && cd edu-agent
mkdir -p docs/requirements backend frontend uploads/kb uploads/audio
git init
# 把 5 个工单 md 文件复制到 docs/requirements/ 下，重命名为：
# 工单16-需求分析与功能设计.md
# 工单17-教学场景功能分析及智能备课.md
# 工单18-智能助教.md
# 工单19-个性化学习推荐.md
# 工单20-面试AI复盘.md
```

### 2.2 创建 CLAUDE.md（项目宪法，Claude 每次会话自动读取）

在项目根目录新建 `CLAUDE.md`，内容直接复制：

```markdown
# 教育智能体项目 EduAgent（高职院校教育数字人）

## 项目背景
见 docs/requirements/ 下 5 个工单。共 4 大功能模块：
智能备课(工单17)、智能助教RAG(工单18)、个性化学习推荐(工单19)、面试AI复盘(工单20)。

## 技术栈（严格遵守，不得擅自更换）
- 后端：Python 3.12 + FastAPI + SQLAlchemy + SQLite（backend/）
- 前端：Vue 3 + Vite + Element Plus + ECharts（frontend/）
- LLM：OpenAI 兼容接口（DeepSeek/Qwen），配置从 backend/.env 读取，严禁硬编码
- 向量库：ChromaDB；Embedding：BAAI/bge-m3；重排：BAAI/bge-reranker-v2-m3
- ASR：faster-whisper；文档解析：PyMuPDF/python-docx/python-pptx/openpyxl

## 硬性规范
1. 每个源码文件头部注释必须写工单编号，示例（Python）：
   # 工单编号：人工智能NLP-Agent数字人项目-教育智能体-智能备课任务
2. Git commit 格式：[工单17] 完成教案生成接口
3. Windows 环境：所有文件读写显式 encoding="utf-8"；系统默认编码问题用 chcp 65001 / PYTHONUTF8=1 处理
4. 密钥只放 backend/.env（已在 .gitignore），示例字段见 .env.example
5. API 统一前缀 /api，返回 {code, msg, data} 结构
6. 数据库改动需同步更新 alembic 迁移或 models 注释

## 目录结构
edu-agent/
├── backend/          # FastAPI：app/main.py, app/models/, app/api/, app/services/, app/core/
├── frontend/         # Vue3：src/views/ 按模块分目录 lesson/assistant/learn/interview/
├── docs/requirements/# 5 个工单原文（唯一需求来源）
├── uploads/          # 运行时上传文件
└── CLAUDE.md
```

### 2.3 创建 backend/.env 与 .env.example

```bash
# .env.example（提交到 git；.env 不提交）
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-xxxx
LLM_MODEL=deepseek-chat
EMBEDDING_MODEL=BAAI/bge-m3
HF_ENDPOINT=https://hf-mirror.com
WHISPER_MODEL=medium
JWT_SECRET=change-me
```

并创建 `.gitignore`：`__pycache__/ node_modules/ .env uploads/ dist/ *.db`

### 2.4 安装依赖

```bash
# 后端
cd backend && python -m venv .venv && source .venv/Scripts/activate
pip install fastapi uvicorn sqlalchemy openai python-docx python-pptx openpyxl \
  pymupdf chromadb sentence-transformers faster-whisper python-multipart pydantic-settings -i https://pypi.tuna.tsinghua.edu.cn/simple

# 前端
cd ../frontend && npm create vite@latest . -- --template vue
npm install element-plus echarts axios marked -g --registry=https://registry.npmmirror.com 2>/dev/null || npm install element-plus echarts axios marked --registry=https://registry.npmmirror.com
```

---

## 3. 阶段三：逐工单开发（Day 1～9）

> **通用节奏**：每个工单开一个新会话 → 先让 Claude 出方案（Plan）→ 你确认 → 再让它写代码 → 最后跑测试、提交。
> 每个工单开工前先：`cd edu-agent && claude` 启动，粘贴对应提示词。

### 工单 16：需求分析与架构设计文档（1 人日）

**给 Claude 的提示词（直接粘贴）：**

```
请阅读 docs/requirements/工单16-需求分析与功能设计.md，为本项目生成
《教育智能体需求分析与软件架构设计》文档，输出到 docs/设计文档-工单16.md。

硬性要求：
1. 严格按工单指定的六章结构：一、项目背景；二、需求分析（目标用户/主要功能场景）；
   三、软件设计架构（总体架构图用 Mermaid、详细分层说明）；四、各场景技术选型分析
   （含选型对比表格，至少覆盖：备课生成/RAG检索/推荐引擎/ASR 四个场景）；
   五、数据安全与合规；六、实施建议（资源规划+工时安排，对齐 16~20 号工单的 9 人日）。
2. 技术选型必须与本仓库 CLAUDE.md 声明的技术栈一致。
3. 面向高职院校用户痛点（备课负担、学情差异、行政低效、就业跟踪不足）。
4. 架构参考"端-云"分层：终端层/应用层（4大智能体模块）/能力层（LLM+RAG+推荐）/数据层。
完成后自查六章齐全、Mermaid 语法可渲染。
```

**验收清单：** 六章齐全 ✓ 选型与本仓库一致 ✓ 工时表覆盖 5 工单 ✓

### 工单 17：智能备课（2 人日）

**给 Claude 的提示词（第 1 天，后端为主）：**

```
阅读 docs/requirements/工单17-教学场景功能分析及智能备课.md，实现"智能备课"后端。

先输出（我确认后再写代码）：
1. 数据库表设计：courses(课程)、lesson_plans(生成记录,含版本号)、
   plan_versions(版本快照JSON)、resources(可引用资源)
2. REST 接口清单：生成/列表/详情/编辑保存/新建版本/回滚版本/导出/资源检索

然后实现：
1. POST /api/lesson-plans/generate
   入参：{course_name, chapter, objectives[], content_types[教案,课件大纲,习题,案例]}
   调 LLM（OpenAI 兼容，读 .env）生成结构化 JSON 并入库，流式返回进度
2. 习题生成规格：单选10+多选5+判断5+简答3，每题附答案、解析、知识点标签
3. RAG 引用：POST /api/resources/search 关键词检索校本资源，生成内容中标注 [来源]
4. 导出：GET /api/lesson-plans/{id}/export?format=docx|pptx，用 python-docx/python-pptx
5. 版本管理：每次保存生成快照，支持 diff 对比与回滚
6. pytest 接口测试：生成/保存/版本回滚/导出 四类用例
7. 文件头注释写工单编号。用 uvicorn app.main:app --reload 启动并自测通过。
```

**第 2 天（前端）：**

```
继续工单17：实现智能备课前端（frontend/src/views/lesson/）。

1. 备课表单页：课程名/章节/教学目标/内容类型多选 → 调生成接口，展示生成进度
2. 结果编辑页：按"教案/课件大纲/习题/案例"分 Tab，习题用表格可编辑，
   右侧资源检索面板（搜索→一键插入正文并加引用标注）
3. 工具栏：保存新版本、历史版本列表+回滚、导出 Word/PPT（下载流）
4. Element Plus 组件规范，Axios 统一拦截器，路由 /lesson
跑通全流程后 commit：[工单17] 智能备课前后端完成
```

### 工单 18：智能助教——多模态 RAG（2 人日）

**给 Claude 的提示词（第 1 天，知识库与检索管线）：**

```
阅读 docs/requirements/工单18-智能助教.md（参考 RAG-Anything 思路），实现智能助教后端。

表设计：kb_docs(文档: id, owner_id, owner_type[public/teacher/student], filename,
parse_status)、kb_chunks(块: doc_id, chunk_text, table_md, image_path, page_no)

实现解析入库管线 POST /api/kb/upload：
1. PDF 用 PyMuPDF：逐页抽文本、表格(转Markdown)、图片(存 uploads/kb，记录路径)
2. DOCX/PPTX 用 python-docx/python-pptx 抽文本与表格；XLSX 用 openpyxl 转表格
3. 文本切块 512 tokens / overlap 64；表格整块不切；图片单独成块（MVP 可不做图片理解，
   保留路径用于引用回显）
4. 全部块用 bge-m3 向量化入 Chroma（collection 按 owner 分：public / u_{id}）

实现混合检索 POST /api/kb/search：
1. 向量检索（个人库 top20 + 公共库 top20）与 BM25 关键词检索（自实现打分即可）
2. RRF 融合 → bge-reranker-v2-m3 重排 → 取 top5，返回块内容+来源(文件名/页码)+图表引用
pytest 覆盖：上传PDF→检索命中指定页表格 的用例。文件头注释写工单编号。
```

**第 2 天（问答服务+前端）：**

```
继续工单18：实现问答与前端。

1. POST /api/assistant/chat（SSE 流式）：
   - 取当前用户私有库+公共库混合检索 top5
   - System Prompt：基于以下资料回答，必须标注引用[文件名 p页码]，
     涉及表格输出 Markdown 表格，涉及图片在答案尾部列"相关图表"文件路径
   - 多轮对话：携带最近 6 条历史
2. 前端（frontend/src/views/assistant/）：
   - 我的知识库页：上传(拖拽,显示解析状态)、文档列表、删除
   - 聊天页：流式渲染 Markdown（marked）、引用来源侧栏（点击可预览图片/表格）
   - 路由 /assistant
commit：[工单18] 智能助教多模态RAG完成
```

### 工单 19：个性化学习推荐（2 人日）

**给 Claude 的提示词（第 1 天，画像与图谱）：**

```
阅读 docs/requirements/工单19-个性化学习推荐.md，实现个性化学习后端。

表设计：
- knowledge_points(知识点: id, name, prereq_id 自关联形成图谱) —— 先内置"人工智能导论"
  约 40~50 个知识点及先修关系（如 矩阵运算→神经网络→反向传播→梯度下降）
- questions(题目，从工单17题库导入, 关联知识点)
- attempts(答题记录: student_id, question_id, is_correct, created_at)
- mistake_book(错题本: attempt_id, ai_analysis JSON, variant_questions JSON)
- student_profile(学生画像: knowledge_point_id, mastery[0~1], updated_at)

实现：
1. POST /api/learn/answer 答题接口 → 写 attempts → 更新画像
   （按知识点加权正确率，时间衰减：近7天权重1.0、30天0.7、更早0.4）
2. 画像接口 GET /api/learn/profile/{student_id}：返回各知识点掌握度
3. 路径推荐 GET /api/learn/path/{student_id}：
   找 mastery<0.6 的薄弱点 → 沿知识图谱上溯到最先修薄弱点 → 输出推荐顺序及
   "为什么推荐"（可解释性：因为A未掌握且是B的前置）
4. 自适应练习 GET /api/learn/practice?kp_id=：连续答对3题提升难度档，答错降档
pytest 覆盖：答题→画像更新→推荐路径 三连用例。文件头注释写工单编号。
```

**第 2 天（AIGC 错题本+前端）：**

```
继续工单19：AIGC 错题本与前端。

1. 答错即触发 POST /api/learn/mistake/analyze：
   Prompt 模板（工单要求）：输入{原题干,学生错误答案,正确答案,知识点,常见错误类型}，
   输出 JSON{1.深入浅出的解析 2.错误原因诊断 3.同知识点2-3道变式题(带答案)}
2. 错题本接口：列表/变式题再答（再答错重新分析）
3. 前端（frontend/src/views/learn/）：
   - 仪表盘：ECharts 雷达图(知识点掌握度)、学习路径时间线、今日任务卡片
   - 练习页：答题即时反馈，自适应换题
   - 错题本页：AI解析+变式题练习
   - 路由 /learn
commit：[工单19] 个性化学习推荐完成
```

### 工单 20：面试 AI 复盘（2 人日）

**给 Claude 的提示词（第 1 天，面试列表+导入）：**

```
阅读 docs/requirements/工单20-面试AI复盘.md，实现面试管理后端。

表设计：interviews(学生,岗位名称,面试轮次,面试形式,城市,面试时间,上报人,上报时间,
录音文件路径,状态[待完善/已复盘])

实现：
1. 面试列表 GET /api/interviews：分页+筛选（按学生/上报人）
2. 批量导入 POST /api/interviews/import：openpyxl 解析 Excel 模板
   （模板列：学生|岗位名称|轮次|形式|城市|时间|备注），返回成功/失败行明细
3. GET /api/interviews/import-template 下载模板
4. 录音上传 POST /api/interviews/{id}/audio（保存 uploads/audio，限制 mp3/wav/m4a ≤50MB）
pytest 覆盖导入与上传。文件头注释写工单编号。
```

**第 2 天（AI 复盘管线+前端）：**

```
继续工单20：AI 复盘管线与前端。

1. POST /api/interviews/{id}/review 触发复盘（异步任务）：
   ① faster-whisper(.env 指定模型) 转写录音为带说话人轮次的文本
   ② LLM 分析，输出 JSON：{总分(0-100), 总体评价, 自我介绍点评,
     questions:[{问题,学生回答,得分,点评,优化版回答}], 修改建议[]}
   ③ 存 reviews 表，interviews 状态→已复盘
2. 前端（frontend/src/views/interview/）：
   - 列表页：工单要求的列+操作栏（有录音才显示"AI复盘"图标按钮）、导入按钮+模板下载
   - 详情页：①总体评价卡片(总分+评语) ②问题解析列表(每题打分点评)
     ③面试对话：左AI优化版/右完整记录 左右对照布局
   - 路由 /interview
commit：[工单20] 面试AI复盘完成
```

---

## 4. Claude Code 日常操作手册（每天怎么用）

```bash
cd ~/edu-agent && claude        # 启动交互会话（Git Bash）
```

| 操作 | 命令/快捷键 | 用途 |
| --- | --- | --- |
| 首次生成项目记忆 | `/init` | 自动扫描代码库生成 CLAUDE.md（本文档已提供更精准版本，可跳过） |
| 计划模式 | `Shift+Tab` 切到 **Plan Mode** | 先出方案不动代码，你确认后再执行（强烈推荐每个工单第一步） |
| 压缩上下文 | `/compact` | 会话太长时压缩历史，防止遗忘早期规范 |
| 继续/恢复会话 | `claude --continue` / `claude --resume` | 一天没做完，第二天接着干 |
| 中断 | `Esc` | 生成跑偏立刻打断 |
| 接受编辑 | 终端提示中选 Yes / `Alt+Y` 全部接受 | 批量写文件时提速 |
| 查看改动 | 让它执行 `git diff` 或自己看 | 每次大改动后人工扫一眼 |

**三条铁律：**
1. **一个工单一个会话**：会话开始第一句永远是"阅读 docs/requirements/工单XX-xxx.md"。
2. **先 Plan 后码**：大功能先按 Shift+Tab 进 Plan Mode 看方案，方案对了再放行，返工率下降 80%。
3. **小步提交**：每完成一个接口/页面就让 Claude `git commit`，commit message 带 [工单XX] 前缀——这同时就是工单要求的"代码注释含工单编号"之外的留痕。

---

## 5. 9 天排期总表

| 天 | 内容 | 里程碑验收 |
| --- | --- | --- |
| Day 0 | 环境+初始化（本文档第 1、2 章） | `claude` 能对话；前后端空项目能跑 |
| Day 1 | 工单16 文档 | 六章设计文档评审通过 |
| Day 2 | 工单17 后端 | 生成接口+导出 pytest 全绿 |
| Day 3 | 工单17 前端 | 浏览器走通：填表→生成→编辑→导出 docx |
| Day 4 | 工单18 解析+检索 | 上传 PDF 能检索到指定页表格 |
| Day 5 | 工单18 问答+前端 | 提问返回带 [引用] 的流式答案 |
| Day 6 | 工单19 画像+图谱+练习 | 答题后画像/推荐路径正确更新 |
| Day 7 | 工单19 错题本+前端 | 答错题生成解析与变式题 |
| Day 8 | 工单20 列表+导入+ASR | Excel 导入成功、录音转写出文本 |
| Day 9 | 工单20 复盘+前端+总联调 | 复盘详情页四区展示正常 |

---

## 6. 常见坑速查（Windows 专项）

| 坑 | 解法 |
| --- | --- |
| 中文乱码 / GBK 报错 | Python 文件读写一律 `encoding="utf-8"`；终端先 `chcp 65001`；或设环境变量 `PYTHONUTF8=1` |
| HuggingFace 模型下载失败 | `.env` 里 `HF_ENDPOINT=https://hf-mirror.com`（bge/whisper 模型都靠它） |
| pip / npm 慢 | 清华源 / npmmirror（命令见第 2.4 节） |
| LLM 返回 JSON 解析失败 | 让 Claude 在调用处加"重试一次 + 宽松解析（正则提取 {} 块）"；DeepSeek 可用 `response_format={'type':'json_object'}` |
| 上传录音 413 | FastAPI 默认无限制，但要检查前端 axios 超时 & uvicorn `--timeout-keep-alive`；50MB 限制自己在代码里判 |
| whisper 转写慢 | 开发期用 `small` 模型，验收演示换 `medium`；CPU 也就慢一点 |
| Chroma 首次启动慢 | 正常现象，在下载默认模型；确认 HF 镜像已配置 |
| Claude Code 在 PowerShell 异常 | 换 Git Bash 运行 |
| API Key 泄露 | 只放 `.env`，`.gitignore` 必须先建再 commit；泄露的 Key 立刻在控制台吊销 |

---

## 7. 最终交付物对照（工单要求 ⇄ 本方案）

| 工单要求 | 落地位置 |
| --- | --- |
| UML/接口/数据库设计 | docs/设计文档-工单16.md + 各工单 Plan 阶段输出 |
| 前后端核心功能代码 | backend/ + frontend/（文件头含工单编号） |
| 测试用例及结果 | backend/tests/pytest_工单*.py + 运行截图 |
| 教案/课件/习题/试题自动生成 | 工单17 生成接口 + 前端编辑导出 |
| 公共/私有知识库+混合检索+引用 | 工单18 RAG 管线 |
| 学生画像+错题本+推荐 | 工单19 |
| 录音→复盘分析 | 工单20 管线 |

> 提示：每个工单完成当天，把演示页面录屏/截图存到 `docs/evidence/工单XX/`，验收材料一次到位。

