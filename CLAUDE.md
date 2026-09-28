# CLAUDE.md — 教育智能体平台（阶段一 16~19 已验收；阶段二 + 工单 21/22/23 已交付）

> 本文件是项目"宪法"。你在本项目的每次会话都必须先遵守本文件；若工单原文与本文件冲突，以工单原文为准并提醒用户。

## 1. 你的角色与总目标

你是本项目的全栈工程师，负责"AI 教学智能体"Web 平台的持续开发。**需求唯一来源是 `docs/requirements/` 下的 5 个工单**，其中**本期已开发 4 个：按 16 → 17 → 18 → 19 顺序**（工单 19 的题库来自工单 17 的试题生成，不可颠倒）。**工单 20（面试 AI 复盘）已移出交付范围**（用户 2026-09-17 决策）：需求原文仍在 `docs/requirements/工单20-面试AI复盘.md`，设计作为**存档**保留在 `docs/设计文档-工单16.md`。**不要实现工单 20，也不要删除其文档存档。**

> **当前实际状态（2026-09-27 核对）**：阶段一（工单 16~19）与阶段二已验收；**工单 21/22/23 已交付**（**均无需求原文**，见第 8 节对应小节）。**工单 23 于 2026-09-27 交付**（设计 `docs/设计文档-工单16.md` **v1.6**，计划 `docs/superpowers/plans/2026-09-27-班级学情闭环.md`，台账 `docs/进度记录.md §四之五`）。**设计文档是唯一设计依据**——v1.6 已把工单 21/22 按已交付事实回补，不再有"代码里有、文档里没有"的模块。**下一步是阶段三（云端数字人 API），需商务采购落地才能启动**。

功能域（含追加交付）：
- **智能备课**（工单17）：教案/课件/习题/案例/试题自动生成、编辑、版本管理与回溯、导出 docx/pptx
- **智能助教**（工单18）：多模态文档上传解析、公共/私有知识库、混合检索+重排、带引用的流式问答
- **个性化学习推荐**（工单19）：知识图谱、学生画像、学习路径推荐、自适应练习、AIGC 错题本
- **虚拟教室 / 成课**（工单21，无需求原文）：教案 → 讲课视频（**核心管线在仓库外**）
- **沉浸式助教台**（工单22，无需求原文）：问答页舞台化 + 数字人人设/闲聊 + 浏览器语音提问（**零新增路由**，但**改了既有接口契约与内部回答分支**——不是"纯前端"，见「工单 22」小节）
- **班级学情闭环**（工单23，无需求原文，**已交付 2026-09-27**）：学情回流给教师 + 备课跟着学情走
- ~~**面试 AI 复盘**（工单20）~~：Excel 批量导入、录音上传转写、LLM 复盘分析 —— **不做，设计存档，见第 8 节**

### 阶段划分（**严格串行，前一阶段全部验收后才启动下一阶段**）

- ~~**阶段一 = 当前唯一任务**：纯文本 Web 系统（"AI 教学大脑"），即工单 16→17→18→19（**工单 20 已移出本期**）。~~
  **✅ 已于 2026-09-17 完成并验收**（240 条 pytest 全绿、80/80 浏览器断言通过、验收截图落盘、DoD 五条齐活）。
- ~~阶段二 = 数字人形象层：前端 2D 虚拟形象 + TTS + 音量驱动口型；数字人层抽象为可替换 provider（形象驱动 / TTS 各一个接口 + 一个本地实现）~~
  **✅ 已于 2026-09-17 完成**（Edge-TTS + 音量驱动口型，43 条 pytest 全绿、14/14 浏览器断言通过；只挂智能助教问答页）。详见第 8 节末「阶段二」小节。**形象库扩展（6 写实 + 1 Live2D）后续于 2026-09-18~20 交付**——卡通脸 `svg-face` 同日退役，见下一小节「阶段二增量 · 形象库扩展」。
- **✅ 追加交付（16~19 与阶段二之后，不属上述串行链，均已完成）**：
  - **工单 21 · 虚拟教室 / 成课**：把教案变成可播放的讲课视频（详见「工单 21」小节）
  - **工单 22 · 沉浸式数字人助教台**：问答页重排为以数字人为主体的舞台 + 浏览器语音提问（详见「工单 22」小节）
  - **工单 23 · 班级学情闭环**：学情回流给教师 + 备课跟着学情走（**已交付 2026-09-27**，见「工单 23」小节）
- 阶段三 = 接入云端数字人 API（臻灵 / 讯飞虚拟人）：**TTS 一路只改 provider 配置**；**形象一路不是**——云端返回的是**视频流**（H.264/WebRTC）而非"照片 + 口型参数"，本地 `render` / `computePose` 契约装不下它。详见 `docs/讲解文档-平台说明.md` 6.1 节。
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
   ~~⚠️ **前置动作**：本仓库当前**尚未 `git init`**……~~ —— **本条已完成**（v1.6 勘误 2026-09-27）：仓库早已初始化并有完整提交历史。**只做本地 commit，不 push**（gitee 与 GitHub 都不推，用户拍板）。
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
| 数字人形象（阶段二） | **前端渲染器** + Web Audio API（`AnalyserNode` 读音量驱动口型），**零 GPU**。现为 `photo`（写实照片 talking-photo，全像素 warp）/ `live2d`（WebGL）；~~`svg-face` 卡通脸~~ 已于 2026-09-18 退役。详见「阶段二增量 · 形象库扩展」 |
| 测试 | pytest + httpx（FastAPI TestClient）；阶段二起 `asyncio_mode="auto"` |

> 阶段三才会引入：云端数字人 API（臻灵 / 讯飞虚拟人）。**TTS 一路确为「换 provider 不改业务代码」；形象一路不是**——云端返回视频流，本地 `render`/`computePose` 契约装不下，需改舞台壳。见第 1 节阶段三与 `docs/讲解文档-平台说明.md` 6.1。

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
│   │   ├── schemas/           ← Pydantic 模型（注意：工单21 的请求模型内联在 api/lecture.py，未单独建文件）
│   │   ├── api/               ← 路由：auth/ lesson/ kb/ assistant/ learn/ lecture/〔21〕teach.py〔23〕tts/〔阶段二〕
│   │   └── services/          ← 业务逻辑；llm_client.py / prompts.py / retriever.py / tts.py〔阶段二〕/ avatar_persona.py〔22〕/ class_profile.py〔23〕
│   ├── tests/                 ← pytest，文件名 pytest_工单XX_功能.py（阶段二用 pytest_阶段二_数字人.py）
│   ├── scripts/               ← capture_evidence.py（浏览器取证）/ seed_class.py〔23 造演示班级〕/ migrate_w19.py / seed_learn.py 等
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── api/               ← axios 实例与各模块 api（含 tts.js〔阶段二〕/ lecture.js〔21〕）
│       ├── audio/             ← 〔阶段二〕sentenceSplitter.js（切句）/ speechQueue.js（合成队列 + 音量分析）/ asr.js〔22 浏览器语音识别〕
│       ├── avatar/            ← 〔阶段二〕provider.js（形象驱动 provider）/ faces.js（形象库清单）
│       ├── views/lesson/ assistant/ learn/ lecture/〔21〕teach/〔23〕
│       ├── router/  store/  components/   ← components 含 AvatarPhotoCanvas.vue/AvatarLive2D.vue〔形象库〕与 AvatarSpotlight.vue〔22 舞台壳〕
│       ├── utils/             ← 〔2026-09-28〕markdown.js：**全站唯一的「Markdown + 公式」渲染入口**，
│       │                        6 个渲染点（问答页/讲课页/引用卡/错题本/练习页/备课预览）都走它
│       ├── styles/            ← main.css（全局）+ markdown.css（公式的公共样式，随 markdown.js 自动引入）
│       └── App.vue            ← 侧边栏导航（按角色隐藏教师/学生专属项）
├── data/                      ← SQLite + Chroma + tts_cache 持久化（gitignore）
└── uploads/                   ← 上传文档与录音（gitignore；含 uploads/lectures/〔21 成课产物〕）
```

## 5. 算力策略（无 GPU，本地只跑业务逻辑）

| 能力 | 执行方案 |
| --- | --- |
| LLM 生成/分析 | 云端 DeepSeek/Qwen API |
| Embedding | 云端 API（.env：EMBEDDING_PROVIDER=api）；离线兜底本地 bge-small-zh-v1.5 |
| 重排序 | 云端 API；开发期 RERANK_ENABLED=false 先跳过，验收前开启 |
| ASR 转写 | 本地 faster-whisper small + int8（14 核 CPU 接近实时，够用）——**随工单20 移出本期，不安装** |
| 数字人渲染 | ✅ 阶段二已做：前端 2D 形象（写实照片 / Live2D）+ **Edge-TTS** + 音量驱动口型，**全程零 GPU**。⚠️ 工单21 的**成课**是另一条路——它跑的是仓库外 wav2lip 管线（CPU 可跑，但需 ~400MB 权重，不入库） |

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
- **路由/菜单级的角色门禁，唯一声明处是路由 `meta.roles`**（2026-09-28 起）：侧边栏由它派生
  （`App.vue`），守卫按它拦截（`router/index.js`）。新增页面时**只加一条 `meta.roles`**，
  不要再在侧边栏手写 `v-if="isTeacher()"`——那正是"菜单按有没有页面渲染、后端按角色授权"
  两套规则漂移的成因（学生点「我的备课」吃 403 就是这么来的）。
  ⚠️ **这不等于页面里不能再判角色**：**动作级**的判断仍归页面，且必须留着——如
  `Knowledge.vue` 的公共库上传按钮（学生传公共库后端回 403）、`Path.vue` 的知识点治理抽屉
  （`/api/learn/kp/*` 是 `require_teacher`）。**路由级管"进不进得来"，动作级管"进来后能点啥"**，
  两条并存、不冲突；删掉动作级守卫会让按钮点下去才报错。
  `meta.title` 是顶栏标题、`meta.menu` 是菜单项文字（缺省取 title）；admin 在 `hasRole()` 里
  与后端 `require_role` 一致地放行。

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

> **2026-09-28 追加（公式渲染收口 + 知识库埋公式）**：
> - **前端渲染只有一个入口**：`frontend/src/utils/markdown.js` 的 `renderMarkdown()`。
>   6 个渲染点（问答页 / 讲课页 `/lecture` / `CitationList.vue` 的引用卡与「查看原文」/
>   错题本 / 练习页 / 备课预览）**全部改调它，不要再各写一份 `marked.parse`**——
>   之前 6 份里 5 份没有公式，`\frac` 会原样显示成源码。样式在同目录 `styles/markdown.css`。
> - **两条不变量**（写在 `markdown.js` 顶部，改动前先读）：公式必须**先抽占位符再进 marked**；
>   行内 `$..$` 必须过 `looksLikeMath` 守卫（与 `services/tts.py::_looks_like_math` 是同一条规则，
>   **改一处要连另一处一起改**）。
> - **种子 PDF 里埋 LaTeX 只能用 base-14 拉丁字体**（`seed_kb.insert_tex`）：
>   `china-s` 会让 PyMuPDF 抽文本时逐字插空格，`\frac` → `\ f r a c`，且**不报错**。
> - 证据：`capture_evidence.py --stage kb-formula`，**12/12 断言**，截图在 `docs/evidence/知识库公式/`。

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

**新增文件**：后端 `services/tts.py`、`api/tts.py`（`GET /api/tts/config`、`GET /api/tts/voices`、`POST /api/tts/speak` 返回音频字节流，**不包 `ApiResponse`**）；前端 `api/tts.js`、`audio/sentenceSplitter.js`、`audio/speechQueue.js`、`avatar/provider.js`、`store/avatar.js`，**以及 `components/AvatarStage.vue`（该文件已于 2026-09-18 删除，其位置现由工单 22 的 `components/AvatarSpotlight.vue` 承担——见「工单 22」小节）**。**挂载位置仅智能助教问答页 `Chat.vue`**，不动 `api/assistant.py` 的 SSE 契约。

**四条职责边界（改代码前先读）**：

1. **前端只管「在哪切句」，后端只管「怎么念」。** 切句必须在前端（要低延迟——首句不等整篇 `done` 就要开念）；Markdown 清洗必须放后端（前端无测试框架，而这段最易出错）。清洗后为空 → 后端回 400，**前端把 400 当「正常跳过」而非失败**（否则一篇回答里出现 3 个表格行就会误判「服务不可用」而停掉后续朗读）。
2. **AudioContext 必须在用户手势的同步栈里创建/恢复**（`handleSend` 内、且在任何 `await` 之前）——一旦中间 await 过，浏览器就认为不是用户发起，autoplay 策略会挂起音频。
3. **音量绝不能进 Vue 响应式。** 问答页每次 delta 都全量重跑 `marked.parse()`，已是热路径；音量再逐帧触发重渲染会直接卡死。做法是 rAF 直写 SVG 的 `d` 属性，只有 `speaking` 走响应式。
4. **`decodeAudioData` 不可取消** → 用世代计数器（generation）让所有在途回调失效；`stop()` 挂在四处（停止生成 / 新建会话 / 切会话 / 组件卸载）。

**验收**：43 条 pytest 全绿（**绝不真联网**，monkeypatch 掉合成实现）+ `capture_evidence.py` 的 avatar 场景 14/14 断言。关键两条断言是「音量峰值 > 0」「发声期间口型形状种类数 > 5」——**证明口型确由音频驱动，而不是按固定节奏播放的假动画**。

**阶段三怎么接**：新增一个 provider 实现并在模块里登记，改 `.env` 的 `AVATAR_PROVIDER` / `TTS_PROVIDER`。

⚠️ **勘误（v1.6，2026-09-27）**：本句原结尾是"**问答页与舞台代码不动**"——**TTS 一路成立**（语音乐是音频流，`synthesize()` 契约可复用），**形象一路不成立**：云端数字人 API 返回的是**视频流**（H.264 / WebRTC），本地 `render` / `computePose` 契约装不下它。准确接法与工作量评估见 `docs/讲解文档-平台说明.md` 6.1 节。

### 阶段二增量 · 形象库扩展〔2026-09-18~20 交付〕

阶段二原本只有 `svg-face` 一个纯代码卡通脸。本次扩为**形象库**：`avatar/faces.js` 定义 6 位写实形象 + 1 位 Live2D，设置弹层可切换、即时生效、落 `localStorage`。

| 档位 | 实现 | 说明 |
| --- | --- | --- |
| 写实照片（6 位） | `components/AvatarPhotoCanvas.vue` | talking-photo：照片 + **全像素 warp** 口型（2026-09-18 由 v2 几何形变重写为 v3 全像素）；png 素材在 `frontend/src/assets/avatar/`，共约 14MB |
| Live2D（小满） | `components/AvatarLive2D.vue` | WebGL 渲染（`pixi-live2d-display` + Cubism2 core），**懒加载**；**不参与工单21 成课**（无对应人像素材与口型驱动） |

> ⚠️ **撞号提醒**：这 5 个文件（`faces.js` / `provider.js` / `store/avatar.js` / `AvatarPhotoCanvas.vue` / `AvatarLive2D.vue`）的文件头标 `[工单20]`，`docs/evidence/工单20/` 装的也是形象库截图——但 **`工单20` 在本文档其余位置的语义是"面试 AI 复盘"**（见「工单 20」小节）。一号两用，**尚未统一**（改名会牵动文件头与已交付的证据路径，需单独拍板）。顺着 `[工单20]` 找需求会找到另一件事。

### 工单 21 · 虚拟教室 / 成课〔**无需求原文**，2026-09-20~22 交付〕

把工单 17 的教案/课件变成**可直接播放的讲课视频**。**代码在 `backend/app/api/lecture.py` + `frontend/src/views/lecture/Room.vue`，但核心算力在仓库外**。

- **链路**：`/lecture/draft`（切页 + 剥 Markdown）→ 教师编辑 → `/lecture/generate`（落 `spec.json` 起子进程）→ 仓库外 `C:/Users/23772/sx/wav2lip/gen_lecture.py`（逐段 edge-tts + Wav2Lip 对口型 + ffmpeg concat）→ `compose_studio.py` 合成 1920×1080 演播室版式 → `/api/lecture/media` 静态下发 → 前端 `timeupdate` 驱动翻页 + 字幕。
- **无新表、无 service 文件**：编排内联在路由里；任务状态在**内存 `_JOBS`**（进程重启即丢）；配置以 JSON 落盘。
- **四条接口**：`POST /draft`、`POST /generate`、`GET /jobs/{job_id}`（以上 teacher）、`GET /courses`（登录用户），外加 `/api/lecture/media` 静态挂载（**无鉴权**）。
- **三条技术债**（改这块前先看）：① `WAV2LIP_DIR` / `PYTHON` **硬编码**，未走 `.env`；② `_JOBS` 内存态；③ media 挂载无鉴权。
- 验收：`pytest_工单21_虚拟教室.py` 9 条（**管线被 mock**）+ `stage_lecture_room` 5 条断言 / 3 张截图。

### 工单 22 · 沉浸式数字人助教台〔**无需求原文**，2026-09-21~22 交付〕

把问答页从"数字人是第三块并列元素"重排为**以数字人为主体的舞台**，并给数字人配上人设与语音提问。

- **25-75 双栏**：左 `.desk-side` 会话列表 + 检索设置（下沉到底部）；右 `.desk-stage` = `AvatarSpotlight` 舞台（占高 80%）+ 悬浮输入条 + 引用抽屉。旧 `.chat-layout` 系列类名**全仓零命中**（整体替换，无开关）。
- **语音提问**：`audio/asr.js` 封装 **浏览器 Web Speech API**（`continuous=false` + `interimResults=true`，final 到手即 `stop()` 并自动发送）。**与服务端 ASR 是两条互不相干的路**——`faster-whisper` 仍不装。
- **状态胶囊**：待命中 / **倾听中**（注意不是"聆听中"）/ 思考中 / 回复中。
- ⚠️ **勘误（v1.6）**：原写"纯前端、零后端改动、SSE 契约逐字未改"——**不成立**。准确口径是：**零新增路由、零新增表**，但实际改了 16 个文件（后端 6 个）：
  - `ChatRequest` 加**可选** `avatar_id`；`api/assistant.py` 新增**闲聊短路分支**（`avatar_persona.is_smalltalk()` 为真则**跳过检索**，走 `_SYSTEM_CHITCHAT` 按人设应答）——解决"问'介绍一下你自己'却回'知识库中未找到依据'"；
  - `POST /api/tts/speak` 加形象级 `rate`/`pitch`（**白名单正则防 prosody 注入**，`pitch` 空串不传否则断流）；
  - **SSE 事件结构**（`sources/delta/done/error`）确实未改。
- 验收分两半，**界线要清楚**：**后端有人设/短路的 8 条用例**（挂在 `pytest_工单18_智能助教.py` 的 `TestAvatarPersonaAndSmalltalk`，**不在本工单名下**——这是"工单 22 无测试"印象的成因）+ 2 条在 `pytest_阶段二_数字人.py`；**前端无任何自动化验证**，只有 `stage_desk_layout` 6 条**布局类**断言 + 3 张截图。**"倾听中"是人工演示项**（无头浏览器拿不到麦克风），不要把前端半边算作已机器验证。

### 工单 23 · 班级学情闭环〔**已交付 2026-09-27**，无需求原文〕

**一句话**：学情回流给教师（班级实体 + 教师学情看板）+ 备课跟着学情走（生成时注入本班学情）。
**闭环**：学生答题 → `attempts` → 画像 → 班级聚合 → 注入备课 Prompt → 教案 →（**零改动**）`/lecture/draft` → 数字人讲课。
最后一跳是设计上的验证点：`/lecture/draft` 本就从**备课内容**构造成课配置，学情经教案自动抵达讲课，**没有碰 `api/lecture.py` 一行**。

- 设计与接口见 `docs/设计文档-工单16.md` **2.2 场景五 / 3.2.2 第(5)组 / 3.2.8**；实施计划见 `docs/superpowers/plans/2026-09-27-班级学情闭环.md`；交付清单与演示动线见 `docs/进度记录.md` **§四之五**。
- **两条口径铁律**（改这块代码前先读）：① 聚合用 **mean-of-means**（先按学生平均、再按人平均），**不是** pooled——学生作答数不等时，pooled 会让刷题多的学生权重畸高；② 覆盖率必须随聚合返回（`student_count` / `class_size`）——"42%" 若只来自 30 人中的 1 人，**误导比没有更糟**。
- **交付物**：新增后端 7（`models/teach.py` / `services/class_profile.py` / `schemas/teach.py` / `api/teach.py` / `scripts/seed_class.py` / 测试 / `migrations.py` 文案）+ 前端 3（`api/teach.js` / `views/teach/ClassInsight.vue` / `main.css` 样式）；修改后端 5（`services/learn_profile.py` / `services/prompts.py` / `api/lesson.py` / `schemas/lesson.py` / `main.py`）+ 前端 3（`router/index.js` / `App.vue` / `views/lesson/Generate.vue`）。
- **接口 6 条**（`/api/teach/*`，均 `require_teacher`；**非本人班级一律 403**）：建班 / 班级列表（学生看到的是"我已加入的"）/ 加成员（按用户名批量，**逐行成败明细**）/ 移成员 / 学生清单（带薄弱数）/ **看板 `insight`**。
- **`learn_profile._compute(db, student_ids)` 是聚合内核**，返回 `{kp_id: {student_id: 记录}}`——**多留的学生维度就是 mean-of-means 与本班覆盖率的来源**，做班级聚合时必须走它，不要另写"按 kp_id 求和"。它对工单19 是纯重构：`compute_mastery` 签名/返回值/边界行为全不变。
- **Prompt 注入唯一入口是 `prompts.py::_common_context()`**，触发条件是 `GenerateRequest.class_id` 非空；教案模板的 `## 三、学情分析` 走 `{learn_analysis_hint}` 的**两个互斥分支**（有学情=要求引用真实数字且"数据中没有的一律不得出现"；无学情=回退到泛化提示）。**不要在别处再插学情文本**。
- **验收**：19 条 pytest + `/api/teach` 6 条路由零回归（全量 324 → **343 passed**）；`capture_evidence.py` 的 `class-insight` 场景 **11/11 断言**，截图存 `docs/evidence/工单23/`。该场景**只读不写库**（跑完 MD5 与跑前一致，见 `docs/进度记录.md` §八 第 37 条）。
- **明确不做**：学生看自己在班里的位次（**只给聚合、不给个体排名**，隐私）；教师布置作业给学生（学生端待办 + 状态流转）；跨班/教研组横向对比、Excel 批量建班；班级-课程-知识点三层关联、选课、学期、成绩单（做深了就变成教务系统）；Embedding 向量化画像；平台浏览埋点。以上均为**后续演进项**，不是遗漏。
- **演示前的状态依赖**：演示班「人工智能2401班」+ 30 个学生账号**已在开发库里**（`classes` 1 / `class_members` 30）。**不要重跑 `seed_class.py`**；还原演示库用 `data/edu_agent.db.bak-pre23`——**`bak-demo` 已过期，用它会把演示班删掉且页面不报错**（详见 `docs/进度记录.md` §六）。

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

## 11. 已知缺口与技术债

1. **《教学场景智能体设计.pdf》不在仓库中**——工单 17/18/19 均以"根据《教学场景智能体设计.pdf》中的各个核心模块的流程梳理"为依据，但该附件缺失。目前以工单原文正文为准；用户提供后需回补核对。
2. ~~**sentence-transformers 当前不可用**~~ —— **已于 2026-09-17（工单18 期间）修复**：根因是 conda 版 scipy/sklearn/pandas 是针对 numpy 1.x 编译的，与 numpy 2.5.x 冲突；已用 pip 升到 numpy 2 版轮子（`scipy 1.18.1` / `scikit-learn 1.9.1` / `pandas 3.0.5`）。本地兜底 Embedding 现可正常使用（`EMBEDDING_PROVIDER=local`，bge-small-zh-v1.5，CPU），实现改为 `transformers` + `torch` 手写 CLS 池化以避开 sklearn 依赖链。踩坑记录见 `docs/进度记录.md` 第八节。
3. ~~**faster-whisper 未安装**，工单 20 开工前需安装。~~ —— **本项随工单 20 移出而作废**（v1.2）：**不需要安装 faster-whisper**（已无服务端音频消费方）。将来若重启工单 20，再按第 3 节选型安装。**注意别与工单 22 混淆**：工单 22 的语音提问走浏览器 Web Speech API，零后端。
4. **工单 21 的成课管线不在仓库内**（v1.6 新增）：`gen_lecture.py` / `compose_studio.py` + ~400MB 权重位于 `C:/Users/23772/sx/wav2lip/`，**换机部署即成课不可用**（返回 503）。仓库**不自包含**，演示前须确认该目录在。
5. **`WAV2LIP_DIR` / `PYTHON` 硬编码**（v1.6 新增）：在 `backend/app/api/lecture.py`，违反第 5 节"代码中不得硬编码"。修法是移入 `.env`（如 `LECTURE_PIPELINE_DIR` / `LECTURE_PYTHON`）——**改动会牵动成课链路，需单独回归**，故尚未执行。
6. **`[工单20]` 一号两用**（v1.6 新增）：形象库的 5 个前端文件头与 `docs/evidence/工单20/` 用的是"工单20=形象库"，与第 8 节"工单 20 = 面试 AI 复盘"**撞号**。**未统一**——改名牵动文件头与已交付证据路径，需单独拍板。
7. **工单 22 的前端半边无自动化验证**（v1.6 新增）：后端 8+2 条 pytest **挂在别的测试文件里**（`pytest_工单18_智能助教.py` / `pytest_阶段二_数字人.py`），**没有自己的测试文件**；前端只有布局类浏览器断言。"倾听中"状态是**人工演示项**（无头浏览器拿不到麦克风），**不要把它算作已机器验证**。
8. **`/api/lecture/media` 静态挂载无鉴权**（v1.6 新增）：`app.mount` 绕过 `Depends`。当前按"校内公开课件"对待；若课程内容含学情，须改带鉴权的 `FileResponse`。
9. **仓库无前端单测框架**（v1.6 新增，2026-09-27 更正）：`frontend/package.json` 无 vitest/jest，前端正确性只能靠 `npm run build` + `capture_evidence.py` 兜底。
   ⚠️ **但别据此以为工单 23 的前端没验证过**（2026-09-27 更正）：`class-insight` 场景有 **11 条断言**覆盖看板渲染、ECharts 真出图（`canvas >= 2`）、学生清单 30 行、跳转后学情预览正文——**是机器验证过的**。
   **真正没有自动化验证的是工单 22 的前端**（只有 6 条布局类断言 + 3 张截图；"倾听中"是人工演示项），见第 7 条。
   📌 **前端并非只能靠"看"**（2026-09-28 补充）：侧边栏角色门禁有独立场景 `--only gate`，
   **23 条断言**覆盖两个角色各自的菜单可见项 + 硬敲对方专属 URL 被弹回 + 根路径与
   `/learn` 的角色化重定向，证据在
   `docs/evidence/角色门禁/`（**故意不塞进某个工单的连续编号流**——它跨 17/19/23）。
   该场景**只读不写库**，跑完 MD5 与跑前一致即证明。
   数学公式同理有独立场景 `--stage chat-formula`（**8 条断言**，`docs/evidence/公式渲染/`，
   同样跨工单——它同时压 工单18 的问答页渲染与 阶段二 的朗读清洗）。**它必须真问一次大模型**：
   公式能从 prompt 里长出来本身就是被验证的一半，只断言"页面能渲染我塞进去的字符串"
   会漏掉 prompt 没生效这种失败。
10. **⚠️ `capture_evidence.py` 有 3 个 stage 的选择器已失效**（2026-09-28 新增）：
   工单22 把问答页类名整体换成 `.desk-*` / `.thread-*` / `.stage-*` 并删掉 `.avatar-svg`，
   却只更新了自己新建的 `desk-layout` 场景，**没回头修** `assistant-chat`（工单18）、
   `learn-related-chat`（工单19）、`avatar-speech`（阶段二）。这三个**现在跑必然超时**，
   §四之三/四之四 里 80/80、14/14 的成绩是改造**之前**跑的。**未修，属技术债**。
   教训：**重命名一批 CSS 类时要 `grep` 取证脚本**——选择器是跨文件的隐式契约，
   编译器一句都不报。新增的 `chat-formula` 用的是当前选择器（已实跑 8/8）。
11. **取证脚本的截图编号是「按工单号连续」的**（2026-09-28 新增）：两条场景若共用同一个
    ticket（目录），**各跑各的时候会各出现一套 `01-`/`02-`**。文件名不同故不会真覆盖，
   但同一目录里两套编号看着就是错的。**跨工单的场景一律独立成目录**
   （`角色门禁` / `公式渲染` / `知识库公式` 都是这么来的），别为了"放一起好找"而共用一个。
12. **`backdrop-filter` 会给 `position: fixed` 的后代当包含块**（2026-09-28 新增）：
   问答页引用抽屉 `.cites-panel` 带 `backdrop-filter: blur(14px)`，挂在它里面的
   「查看原文」`el-dialog` 于是**以 366px 宽的面板为准居中，右侧 361px 甩出视口**（实测）。
   已用 `append-to-body` 修掉。**同一组件在检索页没问题**——那里没有这个祖先，
   所以"我这儿好的、你那儿坏的"能同时成立。断言要写成**元素完整落在视口内**
   （`rect.right <= innerWidth`），只断"弹层打开了"抓不到这类问题。
