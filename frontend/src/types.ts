// 与后端 models/task.py 对齐的类型定义（仅前端需要的字段）

export type TaskType = 'simple' | 'creative' | 'manuscript' | 'anchor' | 'poetry' | 'image'

export interface TaskState {
  task_id: string
  task_type?: TaskType
  status?: string
  dir_name?: string
  current_step?: string
  current_status?: string
  current_progress?: number
  current_message?: string
  final_video_file?: string
  idea?: string
  prompt?: string
  manuscript_text?: string
  script_text?: string
  scene_count?: number
  paragraph_count?: number
  paragraphs?: unknown[]
  creative_name?: string
  [key: string]: any
}

export interface TaskListItem {
  task_id: string
  task_type?: TaskType
  status?: string
  creative_name?: string
  idea?: string
  prompt?: string
  manuscript_text?: string
  script_text?: string
  scene_count?: number
  paragraph_count?: number
  dir_name?: string
}

export interface StepDef {
  key: string
  labelKey: string
}

export interface Voice {
  id: string
  name: string
  local_name?: string
  region?: string
  region_code?: string
  gender?: 'male' | 'female'
  lang?: string
  style_tags?: string[]
  preview_text?: string
}

export interface VoiceGroup {
  code: string
  label: string
  count: number
  voices: Voice[]
}

export interface VoiceCatalog {
  languages: VoiceGroup[]
  compat_hint?: Record<string, string[]>
}

export interface Artifact {
  artifact_id: string
  category: 'text' | 'image' | 'video' | 'audio' | 'json' | 'subtitle'
  label_key: string
  step_key: string
  scope_index?: number | null
  size: number
  exists: boolean
  deletable: boolean
}

export interface Workspace {
  path: string
  name?: string
  is_default?: boolean
}
