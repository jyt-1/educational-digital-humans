# AI 教学智能体平台（Education-agent）

面向高职院校 / K12 的 AI 教学智能体 Web 平台，核心是三个功能域 + 数字人形象层：

| 模块 | 说明 |
| --- | --- |
| 智能备课 | 教案 / 课件 / 习题 / 案例 / 试题自动生成、在线编辑、版本管理与回滚、导出 docx/pptx |
| 智能助教 | 多模态文档上传解析、公共/私有知识库、混合检索 + 重排、带引用溯源的流式问答 |
| 个性化学习推荐 | 知识图谱、学生画像、学习路径推荐、自适应练习、AIGC 错题本 |
| 数字人形象层 | 写实照片 / Live2D 数字人 + Edge-TTS 语音朗读 + 音量驱动口型同步（挂在智能助教问答页） |

## 技术栈

- **后端**：Python 3.11+ / FastAPI / SQLAlchemy 2.x / SQLite / ChromaDB / Edge-TTS
- **前端**：Vue 3 + Vite + Element Plus + ECharts + Pixi.js（Live2D）
- **LLM**：OpenAI 兼容接口（DeepSeek / Qwen），Embedding 与重排走云端 API（可本地兜底）——完整清单见下方[模型清单](#模型清单)
- **测试**：pytest + httpx

## 模型清单

平台用到的**全部**模型一览。模型名、base_url、开关一律写在 `.env`（模板见 `.env.example`），**代码中不硬编码**。
下表的「状态」列是**当前 `.env` 的实际取值**（2026-09-20 核对），与 `.env.example` 的出厂默认值可能不同。

### 一、文本生成与分析 —— LLM

| 用途 | 模型 | 接入方式 | 状态 |
| --- | --- | --- | --- |
| 教案 / 课件 / 习题 / 案例 / 试题生成（SSE 流式） | `deepseek-chat` | OpenAI 兼容接口，`LLM_BASE_URL=https://api.deepseek.com/v1` | ✅ 在用（`.env` 已配真实 Key；`GET /api/health` 可查 `llm_configured`） |
| 智能助教带引用问答（SSE 流式） | 同上 | 同上 | ✅ 在用 |
| AIGC 错题分析（深入浅出解析 + 错因归因 + 2~3 道变式题） | 同上 | 同上，`response_format={"type":"json_object"}` + 失败重试 1 次 + 宽松 JSON 提取 | ✅ 在用 |

封装在 `backend/app/services/llm_client.py`（`chat_text` / `chat_stream` / `chat_json`，单次调用超时 120 秒）。
客户端是**通用的 OpenAI 兼容实现**——换 Qwen 或别的模型只需改 `.env` 的 `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY`，代码不动。

### 二、检索（RAG）

| 环节 | 模型 | 维度 / 说明 | 状态 |
| --- | --- | --- | --- |
| 向量化（云端档） | `BAAI/bge-m3` | 1024 维，硅基流动（`EMBEDDING_PROVIDER=api`） | ⏸️ 未启用（`EMBEDDING_API_KEY` 仍为占位符 `sk-xxx`） |
| 向量化（本地档） | `BAAI/bge-small-zh-v1.5` | 512 维，CPU（`transformers` + `torch` 手写 CLS 池化 + L2 归一化） | ✅ **当前生效**（`.env` 里 `EMBEDDING_PROVIDER=local`） |
| 重排序 | `BAAI/bge-reranker-v2-m3` | 硅基流动 `/rerank` 接口 | ⏸️ 未启用（`RERANK_ENABLED=false`；开启后调用失败也**自动降级**，绝不阻断问答） |
| 关键词召回 | BM25（`rank-bm25` + `jieba` 分词） | 非神经网络，与向量召回按 RRF 融合 | ✅ 在用 |

> ⚠️ **两档 Embedding 维度不同（1024 vs 512），而 Chroma collection 建库即固定维度**——切换 provider **必须删掉 `data/chroma` 并重新解析已上传文档**。
> 向量库里的 `.embedding_signature.json` 签名文件会主动拦截并给出提示，召回侧同时自动降级为关键词召回。

### 三、语音（数字人形象层）

| 能力 | 模型 / 服务 | 说明 | 状态 |
| --- | --- | --- | --- |
| 语音合成 TTS | **Edge-TTS**（微软在线神经语音） | 纯 CPU、无需 Key，**需要联网**；合成结果落盘 `data/tts_cache/`，重复语句断网也能播 | ✅ 在用 |
| 语音识别 ASR（浏览器侧） | 浏览器内置 **Web Speech API**（`SpeechRecognition`） | 前端聆听态走浏览器自带识别，**无本地模型**（`frontend/src/audio/asr.js`） | ✅ 在用 |
| 语音识别 ASR（服务端） | `faster-whisper` `small` + int8 | 原为工单 20 准备，**该工单已移出本期，本期不安装** | ⛔ 配置存档，不启用 |

**TTS 音色共 8 个 zh-CN**（清单见 `GET /api/tts/voices`，静态写死不联网）：默认 `zh-CN-XiaoxiaoNeural`（晓雯 / 苏青 / 周慧），
另有 `zh-CN-XiaoyiNeural`（林悦 / 小满）、`zh-CN-YunxiNeural`（陈远）、`zh-CN-YunjianNeural`（吴谦）、
`zh-CN-YunyangNeural`、`zh-CN-YunxiaNeural`、`zh-CN-liaoning-XiaobeiNeural`、`zh-CN-shaanxi-XiaoniNeural`。

### 四、数字人形象（不含生成式模型）

| 档位 | 素材 | 渲染方式 | 开关 |
| --- | --- | --- | --- |
| `photo`（默认） | 6 张写实照片 PNG：晓雯 / 苏青 / 周慧 / 林悦 / 陈远 / 吴谦 | Canvas 逐帧口型 + 眨眼，**音量驱动** | `AVATAR_PROVIDER=photo` |
| `live2d` | `live2d-widget-model-shizuku`（小满，Cubism 2 模型，**本地托管**，不走外网 CDN） | `pixi-live2d-display` 0.4.0 + `pixi.js` 7 + Cubism2 core | 前端形象库内切换 |

> **形象层没有生成式模型**：口型由 Web Audio 的 `AnalyserNode` 实测音量驱动绘制，不是按固定节奏播放的假动画。
> 卡通脸 `svg-face` 档已于 2026-09-18 退役。形象与音色的配对关系见 `frontend/src/avatar/faces.js`。

### 五、本机明确不用的模型 / 组件

| 模型 / 组件 | 不用的原因 |
| --- | --- |
| 任何 CUDA 组件（GPU 版 torch、MuseTalk、LiveTalking） | 开发机无独立显卡（本机为 `torch 2.13.0+cpu`），属硬性红线 |
| `BAAI/bge-m3` 本地推理 | 无 GPU 时加载与推理都慢，本地档一律用 small 级别 |
| MinerU / OCR | 纯 CPU 跑 OCR 极慢；文档解析改用 PyMuPDF / python-docx / python-pptx / openpyxl 自研，公式与复杂版面降级为「保留原文位置 + 引用回显」 |
| `sentence-transformers` | 其依赖链（sklearn / scipy / pandas）在本机 numpy 2.x 下不可用，本地 Embedding 改走 `transformers` + `torch` |

## 目录结构

```
Education-agent/
├── backend/        # FastAPI 后端（app/ 业务代码，tests/ pytest 用例）
├── frontend/       # Vue 3 前端
├── docs/           # 工单需求（requirements/）、设计文档、验收证据（evidence/）
├── data/           # SQLite、Chroma 向量库、TTS 缓存等持久化数据（不入 git）
├── uploads/        # 上传的文档与知识库图片（不入 git）
├── CLAUDE.md       # 开发约定与项目"宪法"
└── .env.example    # 配置模板（复制为 .env 后填写密钥）
```

## 环境要求

- Python ≥ 3.11（Windows 下推荐直接用系统 Python/Anaconda）
- Node.js ≥ 18
- **无独立显卡也能跑**：全部模型调用走云端 API，本地只跑业务逻辑；本机 torch 必须为 CPU 版（禁止安装 CUDA 版组件）
- Edge-TTS 需联网（合成结果会落盘缓存，重复语句断网也能播）

## 快速启动

### 1. 配置环境变量

```bash
# 在项目根目录
cp .env.example .env
```

编辑 `.env`，至少填写：

- `LLM_API_KEY`（DeepSeek 或 Qwen 的 Key）
- `EMBEDDING_API_KEY`（硅基流动等，提供 BAAI/bge-m3 向量化）
- `JWT_SECRET`（改成随机字符串）

其余项（重排开关、TTS 音色、形象 provider 等）默认值即可跑通，详见 `.env.example` 内注释。

### 2. 启动后端（端口 8000）

```bash
cd backend
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
python -m uvicorn app.main:app --reload --port 8000
```

启动后可访问 Swagger 文档：http://127.0.0.1:8000/docs

> Windows 终端中文乱码先执行 `chcp 65001`。

### 3. 启动前端（端口 5173）

```bash
cd frontend
npm install        # 建议走 npmmirror：npm install --registry=https://registry.npmmirror.com
npm run dev
```

浏览器打开 http://localhost:5173 即可使用。Vite 已配置 `/api` 代理到后端 8000 端口，无需处理跨域。

### 4. 测试账号

内置演示账号：**demo_teacher / demo123456**（教师角色），也可在登录页注册新账号（教师 / 学生两种角色）。

## 运行测试

```bash
cd backend
python -m pytest
```

- pytest 配置在 `backend/pyproject.toml`（勿新建 `pytest.ini`：中文 Windows 下 GBK 编码会解析失败）
- 用例文件命名遵循 `pytest_工单XX_功能.py`，阶段二用例为 `pytest_阶段二_数字人.py`

## 常见问题

| 问题 | 说明 |
| --- | --- |
| 前端接口 502 | 后端没起，或 Vite 代理目标不通；确认 uvicorn 已在 8000 端口运行 |
| 朗读没声音 / 朗读失效 | Edge-TTS 需联网；检查系统代理设置，必要时调整 `.env` 的 `TTS_PROXY` |
| TTS 配置改了不生效 | 清浏览器 localStorage 后刷新（历史版本遗留的配置键会覆盖新值） |
| HuggingFace 模型下载失败 | `.env` 中必须配置 `HF_ENDPOINT=https://hf-mirror.com` |
| 安装依赖拉到 CUDA 版 torch | 用 CPU 源：`pip install torch --index-url https://download.pytorch.org/whl/cpu` |

## 更多文档

- 项目背景、架构设计与接口清单：`docs/设计文档-工单16.md`
- 平台功能讲解：`docs/讲解文档-平台说明.md`
- 开发过程与踩坑记录：`docs/进度记录.md`
- 开发约定（AI 协作必读）：`CLAUDE.md`
