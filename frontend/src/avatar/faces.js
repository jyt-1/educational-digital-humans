// [工单20] 人工智能NLP-Agent数字人项目-教育智能体 —— 数字人形象库清单
//
// 一个形象 = 照片 + 五官几何标定（相对坐标 0~1）+ 性别 + 默认音色。
// 坐标来源：.workbuddy/tmp/faces/calibrate.py（OpenCV 级联检测，photo-teacher
// 人工标定交叉验证偏差 ≤1.6%）；尺寸参数按「瞳距」归一推导，构图不同的照片
// 口型/眨眼区域也能跟着脸大小走：
//   mouth.maxRx = 瞳距 × 0.25   mouth.maxRy = 瞳距 × (W/H) × 0.21
//   eyeHalfW    = 瞳距 × 0.227  eyeHalfH   = 瞳距 × (W/H) × 0.1065
// 嘴 cy 统一 -0.010：smile 级联检测中心系统性偏下（photo-teacher 实测偏差）。
//
// render: 'photo' = 写实照片 canvas 逐帧口型；'live2d' = pixi-live2d-display 渲染。
//   与 avatar/provider.js 的 provider.render **同一套词汇**，由 pickRender(face, provider)
//   统一判定用哪个渲染组件（素材决定一张脸只能怎么画，故以形象自带值为准）。
// defaultVoice: 切换形象时自动配对的 edge-tts 音色（用户手动改音色仍可覆盖）。

import photoTeacher from '@/assets/avatar/photo-teacher.png'
import fYoungBlue from '@/assets/avatar/f-young-blue.png'
import fSeniorBurgundy from '@/assets/avatar/f-senior-burgundy.png'
import fLivelyPonytail from '@/assets/avatar/f-lively-ponytail.png'
import mYoungNavy from '@/assets/avatar/m-young-navy.png'
import mSeniorTweed from '@/assets/avatar/m-senior-tweed.png'

export const FACES = [
  {
    id: 'xiaowen',
    name: '晓雯',
    gender: 'female',
    render: 'photo',
    img: photoTeacher,
    defaultVoice: 'zh-CN-XiaoxiaoNeural',
    desc: '温和知性 · 语文/通识',
    geometry: {
      cropBottom: 0.94,
      mouth: { cx: 0.507, cy: 0.48, maxRx: 0.05, maxRy: 0.028 },
      eyes: [
        { cx: 0.41, cy: 0.326 },
        { cx: 0.608, cy: 0.326 },
      ],
      eyeHalfW: 0.045,
      eyeHalfH: 0.014,
    },
  },
  {
    id: 'suqing',
    name: '苏青',
    gender: 'female',
    render: 'photo',
    img: fYoungBlue,
    defaultVoice: 'zh-CN-XiaoxiaoNeural',
    desc: '青年干练 · 数学和科学',
    geometry: {
      cropBottom: 0.96,
      mouth: { cx: 0.5189, cy: 0.4807, maxRx: 0.0412, maxRy: 0.0259 },
      eyes: [
        { cx: 0.4128, cy: 0.3604 },
        { cx: 0.5775, cy: 0.3618 },
      ],
      eyeHalfW: 0.0374,
      eyeHalfH: 0.0132,
    },
  },
  {
    id: 'zhouhui',
    name: '周慧',
    gender: 'female',
    render: 'photo',
    img: fSeniorBurgundy,
    defaultVoice: 'zh-CN-XiaoxiaoNeural',
    desc: '资深沉稳 · 学科带头人',
    geometry: {
      cropBottom: 0.96,
      mouth: { cx: 0.5104, cy: 0.5432, maxRx: 0.0454, maxRy: 0.0286 },
      eyes: [
        { cx: 0.4036, cy: 0.3994 },
        { cx: 0.5853, cy: 0.3979 },
      ],
      eyeHalfW: 0.0412,
      eyeHalfH: 0.0145,
    },
  },
  {
    id: 'linyue',
    name: '林悦',
    gender: 'female',
    render: 'photo',
    img: fLivelyPonytail,
    defaultVoice: 'zh-CN-XiaoyiNeural',
    desc: '活泼元气 · 低年级课堂',
    geometry: {
      cropBottom: 0.96,
      mouth: { cx: 0.5221, cy: 0.4934, maxRx: 0.0403, maxRy: 0.0254 },
      eyes: [
        { cx: 0.4193, cy: 0.3799 },
        { cx: 0.5807, cy: 0.3779 },
      ],
      eyeHalfW: 0.0366,
      eyeHalfH: 0.0129,
    },
  },
  {
    id: 'chenyuan',
    name: '陈远',
    gender: 'male',
    render: 'photo',
    img: mYoungNavy,
    defaultVoice: 'zh-CN-YunxiNeural',
    desc: '青年阳光 · 信息/编程',
    geometry: {
      cropBottom: 0.96,
      mouth: { cx: 0.5072, cy: 0.5237, maxRx: 0.0466, maxRy: 0.0293 },
      eyes: [
        { cx: 0.4141, cy: 0.376 },
        { cx: 0.6003, cy: 0.373 },
      ],
      eyeHalfW: 0.0423,
      eyeHalfH: 0.0149,
    },
  },
  {
    id: 'wuqian',
    name: '吴谦',
    gender: 'male',
    render: 'photo',
    img: mSeniorTweed,
    defaultVoice: 'zh-CN-YunjianNeural',
    desc: '儒雅博学 · 奥赛/进阶',
    geometry: {
      cropBottom: 0.96,
      mouth: { cx: 0.5091, cy: 0.4539, maxRx: 0.0381, maxRy: 0.024 },
      eyes: [
        { cx: 0.4264, cy: 0.3208 },
        { cx: 0.5788, cy: 0.3208 },
      ],
      eyeHalfW: 0.0346,
      eyeHalfH: 0.0122,
    },
  },
  {
    id: 'shizuku',
    name: '小满（二次元）',
    gender: 'female',
    render: 'live2d',
    model: '/live2d/shizuku/shizuku.model.json',
    defaultVoice: 'zh-CN-XiaoyiNeural',
    desc: 'Live2D 档 · 活泼课堂',
  },
]

export const DEFAULT_FACE_ID = 'xiaowen'

/** 按 id 取形象；未知 id 回退到晓雯（改坏 localStorage 不该白屏）。 */
export function pickFace(id) {
  return FACES.find((f) => f.id === id) || FACES[0]
}
