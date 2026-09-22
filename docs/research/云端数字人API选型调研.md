# 云端数字人 API 选型调研（阶段三预研）

> 日期：2026-09-20 ｜ 调研人：阿砚 ｜ 状态：待小江拍板
> 背景：实时问答侧的「视频流级口型」本地不可达（已查证：MuseTalk/LivePortrait 等全需 GPU；
> 本地 Wav2Lip 离线管线已跑通，只覆盖讲课预生成场景）。本文档回答：**要买，买谁、怎么接、多少钱**。
> 目标效果参照：小江 2026-09-20 录屏（某云端数字人 SaaS 智能助教页，写实形象实时问答 + 形象/声音切换）。

---

## 一、结论先行

| 排名 | 方案 | 一句话理由 |
| --- | --- | --- |
| **首选** | **硅基智能 DUIX（H5 SDK）** | 唯一有成熟 **Web/H5 SDK + WebRTC 视频流**、可直接嵌 Vue 前端的方案；有**免费档（5 分钟/天）**可先做 POC 零成本验证；腾讯投资的 AIGC 公司，生态顺 |
| 备选 | 讯飞虚拟人 | 免费试用额度大（个人 2h/企业 10h），但数字人交互档价格不透明（商务定制制） |
| 备选 | 腾讯云数智人 | 腾讯云生态最正规，但 Web 会话走「端渲染授权年包」或「云渲染次数包」，起采偏重 |
| 不推荐 | 百度曦灵（交互侧） | 交互并发 2400 元/月起，视频生成计便宜但**实时交互贵**；更适合直播/批量出视频场景 |
| 不推荐 | D-ID / HeyGen / Simli | 海外服务，国内教育场景网络与合规都不稳 |

---

## 二、逐家对比

### 1. 硅基智能 DUIX（duix.com / duix.guiji.cn）★首选

**产品形态**：2D 真人级实时数字人，WebRTC 视频流（宣称 50fps、口型微表情同步）。

**接入方式（对我们最关键）**：
- H5 SDK：`npm i duix-guiji-light`，纯前端接入 Vue3，官方明确给出接入要点：
  - `duix.init({ sign, containerLable, conversationId, platform })` → 监听 `initialSuccess` → `duix.start()`；
  - `duix.speak({ content, audio })` 支持**文本 + 自备音频 URL** 驱动，`duix.answer({ question })` 支持平台代答；
  - `duix.openAsr()/closeAsr()` 内置实时语音识别（可替代/并存我们的 Web Speech 方案）；
  - `enableLLM=0` 可关掉平台大模型代答——**答案仍由我们后端 RAG 生成，平台只负责"开口说"**，知识主权在自己手里；
  - 官方注意事项：**duix 实例不要放 Vue 的 data/reactive 里**（与我们现有 rAF 直写的经验一致）。
- 服务端 Open API：交互问答 webhook（dh-question → 我们返回 answer），也可完全不用、纯前端 speak() 驱动。

**价格**：
| 档位 | 价格 | 额度 |
| --- | --- | --- |
| Free | $0 | **5 分钟对话/天**，1 并发，1080P，全部 stock 形象，API 可用 |
| Starter | $29/月 | 150 分钟/月 |
| Creator | $59/月 | 300 分钟/月 + 每月 3 个个人形象 |
| Scale | $399/月 | 3000 分钟/月，5 并发，商用授权 |
| 国内云服务 | 约 2000 元/月/并发 | 1080P，低开发量 |
| 定制形象 | 约 9800 元/套（含声音克隆） | 3~5 分钟真人视频克隆 |
| 开源 Mobile SDK | 免费（Android/iOS） | 本地渲染，Web 用不了 |

**适配我们**：Free 档即可跑通 POC（每天 5 分钟够演示）；正式教学一个班同时一人提问=1 并发，Starter/Creator 档（$29~59/月，约 200~420 元/月）大概率够课堂演示。

### 2. 讯飞虚拟人（xfyun.cn）

- **超拟人数字人交互**（表情动作语义贯穿，星火大模型驱动）：个人免费 2 小时 / 企业免费 10 小时（90 天，1 并发）；之后**商务定制报价，价格不公开**。
- 超拟人交互（纯语音，无形象）：低至 0.1 元/分钟；套餐 600 元/50小时 起。
- 有终端 SDK / 服务端 API / 私有化，但 **Web 端实时数字人的公开 SDK 资料少于 DUIX**。
- 适合：想先用免费额度做语音交互验证；数字人形象交互要商务谈。

### 3. 腾讯云数智人（cloud.tencent.com/product/1211）

- 两种接入：**云渲染**（延时约 1.5s，需 10Mbps 带宽，按会话/次数包计费）与**端渲染**（<1s，3D 按会话驱动次数包 / 2D 按 SDK 授权年包，本地需 GPU 跑虚幻引擎）。
- 腾讯智影（zenvideo.qq.com）是它的 SaaS 视频生成侧：照片变脸定制 3999 元/年（30 分钟视频/月）、数字分身 7999 元/年（60 分钟/月）——**这是"离线出视频"，不是实时交互**。
- 适合：如果学校采购走腾讯云渠道顺，这是"名正言顺"的选项；但 Web 实时会话的起采门槛比 DUIX 高，POC 不友好。

### 4. 百度曦灵

- 开放平台：**云渲染 2D 数字人交互 2400 元/月/路**；照片数字人定制 20 元/次、2D 小样本定制 1000 元/次；视频生成 300 元/100 分钟。
- 交互并发价格贵，直播/批量视频才是它的主场。不选。

### 5. 海外（D-ID / HeyGen / Simli）

- 效果好、有免费档，但国内访问不稳、数据出境合规存疑，教育场景不建议。

---

## 三、接进我们系统的样子（以 DUIX 为例）

改动集中在形象层分发，架构不动：

```
AvatarSpotlight.vue（舞台壳，不动）
  └─ provider 分发（faces.js 加 type:'cloud' 档）
       ├─ photo   → AvatarPhotoCanvas.vue   （本地 warp，保留兜底）
       ├─ live2d  → AvatarLive2D.vue        （保留）
       └─ cloud   → AvatarCloudDUIX.vue     （新：容器 div + duix-guiji-light）
后端：答案生成链路完全不动（RAG → answer.text）；
      前端拿到答案后 duix.speak({ content: answer.text })，平台 TTS+口型全包。
      （也可沿用我们 Edge-TTS 的 audio URL 传入 speak()，音色不换。）
ASR：duix.openAsr() 或保留现有 Web Speech，二选一实测。
音色配对：faces.js 每档形象记一个 DUIX voice/音色 ID，沿用现有 defaultVoice 跟随逻辑。
```

**风险与注意**：
1. DUIX 实例不可进 Vue 响应式（官方明说），挂在模块级单例；
2. 浏览器自动播放策略：`start({muted:true})` 起播，用户点击后 `setVideoMuted(false)`——助教台首次交互引导要加；
3. 免费档 5 分钟/天 → POC 够，课堂常态使用必须买档，**预算 200~420 元/月（Creator 档）量级**；
4. 写实形象用平台 stock 库（与录屏竞品同源风格）；想要"我们自己的老师形象"需克隆定制（约 9800 元/套），可后置；
5. 国内 duix.guiji.cn 与国际 duix.com 是两套计费/域名，POC 用哪个先跟商务确认。

## 四、建议的推进节奏

1. **本周可做（0 元）**：注册 DUIX 免费档 → 用 H5 SDK 在 /assistant 页做一个「云端形象」开关档，拿 stock 形象把 speak/ASR 链路跑通 → 和本地 warp/Live2D 同台对比验收；
2. **POC 通过后**：按并发和月时长买 Creator/Scale 档（200~3000 元/月区间，看使用量）；
3. **要自有形象再谈**：克隆定制 9800 元/套，放在验收效果满意之后。

## 五、参考链接

- DUIX H5 SDK 方法与事件：https://docs.duix.com/sdks/h5/methods ｜ 调用流程：https://docs.duix.com/sdks/h5/process
- DUIX 定价（国际）：https://www.duix.com/pricing ｜ 国内：https://duix.guiji.cn
- 腾讯云数智人 SDK 整体介绍：https://www.tencentcloud.com/zh/document/product/1211/65917
- 讯飞超拟人数字人交互：https://www.xfyun.cn/solutions/Multimodel
- 百度曦灵（价格参考页为第三方整理，采购前以官方报价为准）
