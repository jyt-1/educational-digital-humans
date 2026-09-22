// [工单21] 人工智能NLP-Agent数字人项目-教育智能体-虚拟教室/讲课页 —— 成课链路 API
import http from './http'

/** 从教案生成课程配置草稿（teacher） */
export const draftLecture = (planId) => http.post('/lecture/draft', { plan_id: planId })

/** 提交成课任务（teacher）。spec: {plan_id?, title, subject, avatar, pages, segments} */
export const generateLecture = (spec) => http.post('/lecture/generate', spec)

/** 轮询成课任务进度（teacher）。返回 {job_id, course_id, status, progress, message, error} */
export const getLectureJob = (jobId) => http.get(`/lecture/jobs/${jobId}`)

/** 课程列表（师生均可）。[{courseId, title, subject, base}] */
export const listLectureCourses = () => http.get('/lecture/courses')
