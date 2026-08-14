<script setup lang="ts">
import { ref, computed } from 'vue'
import { t } from '@/i18n'
import { appState } from '@/store'
import { useGa } from '@/composables/useGa'
import SimpleForm from './forms/SimpleForm.vue'
import CreativeForm from './forms/CreativeForm.vue'
import ManuscriptForm from './forms/ManuscriptForm.vue'
import AnchorForm from './forms/AnchorForm.vue'
import PoetryForm from './forms/PoetryForm.vue'

const { trackEvent } = useGa()

const taskTypes = [
  { key: 'simple', icon: '🎬🖼️', label: 'ttSimple' },
  { key: 'creative', icon: '🎥', label: 'ttCreative' },
  { key: 'manuscript', icon: '📝', label: 'ttManuscript' },
  { key: 'anchor', icon: '🎙️', label: 'ttAnchor' },
  { key: 'poetry', icon: '📜', label: 'ttPoetry' },
]

// v6.0/6.1 手动模式：暂停点选项（按任务类型）
// creative 细粒度（每个有产物的环节独立，v6.1）；其余粗粒度（PRD §4.3 顺序）
const pausePointOptions: Record<string, { key: string; label: string }[]> = {
  creative: [
    { key: 'image_analysis', label: 'cpImageAnalysis' },
    { key: 'story', label: 'cpStory' },
    { key: 'script', label: 'cpScript' },
    { key: 'character_ref', label: 'cpCharacterRef' },
    { key: 'end_frame_prompts', label: 'cpEndFramePrompts' },
    { key: 'end_frame_gen', label: 'cpEndFrameGen' },
    { key: 'videos', label: 'cpVideos' },
    { key: 'audio', label: 'cpAudio' },
    { key: 'subtitle', label: 'cpSubtitle' },
    { key: 'final', label: 'cpFinal' },
  ],
  manuscript: [
    { key: 'scenes', label: 'cpScenes' },
    { key: 'videos', label: 'cpVideos' },
    { key: 'audio', label: 'cpAudio' },
    { key: 'subtitle', label: 'cpSubtitle' },
    { key: 'final', label: 'cpFinal' },
  ],
  poetry: [
    { key: 'scenes', label: 'cpScenes' },
    { key: 'videos', label: 'cpVideos' },
    { key: 'audio', label: 'cpAudio' },
    { key: 'subtitle', label: 'cpSubtitle' },
    { key: 'final', label: 'cpFinal' },
  ],
  anchor: [
    { key: 'scenes', label: 'cpScenes' },
    { key: 'references', label: 'cpReferences' },
    { key: 'videos', label: 'cpVideos' },
    { key: 'audio', label: 'cpAudio' },
    { key: 'subtitle', label: 'cpSubtitle' },
    { key: 'final', label: 'cpFinal' },
  ],
}

// 手动模式支持的任务类型（simple/simple_image 不支持暂停，PRD §4.3）
const manualSupported = computed(() => !['simple', 'image'].includes(appState.currentTaskType))

// 当前任务类型可选的暂停点
const currentPausePoints = computed(() => pausePointOptions[appState.currentTaskType] || [])

// 默认暂停点（PRD §4.8 预填，用户可增删）
const defaultPausePoints: Record<string, string[]> = {
  creative: ['story', 'script', 'character_ref', 'videos', 'subtitle'],
  manuscript: ['scenes', 'videos', 'subtitle'],
  poetry: ['scenes', 'videos', 'subtitle'],
  anchor: ['scenes', 'videos'],
}

function switchTaskType(type: string) {
  trackEvent('ui_action', { action: 'switch_task_type', type })
  appState.currentTaskType = type
  // 切换任务类型时按 PRD §4.8 预填默认暂停点
  appState.pausePoints = [...(defaultPausePoints[type] || [])]
}

function togglePausePoint(key: string) {
  const i = appState.pausePoints.indexOf(key)
  if (i >= 0) appState.pausePoints.splice(i, 1)
  else appState.pausePoints.push(key)
}

function selectExecMode(mode: 'auto' | 'manual') {
  if (mode === 'manual' && !manualSupported.value) return
  appState.execMode = mode
  if (mode === 'manual' && appState.pausePoints.length === 0) {
    appState.pausePoints = [...(defaultPausePoints[appState.currentTaskType] || [])]
  }
}
</script>

<template>
  <div>
    <!-- v6.0 执行模式条（创建面板全局，PRD §6.1） -->
    <div class="glass-card rounded-2xl p-4 mb-4">
      <div class="flex flex-wrap items-center gap-x-6 gap-y-2">
        <span class="text-sm font-medium text-accent">{{ t('execMode') }}</span>
        <div class="flex gap-2">
          <button
            class="px-4 py-2 rounded-lg text-sm font-medium transition border"
            :class="appState.execMode === 'auto' ? 'bg-accent text-accent-ink border-accent' : 'bg-paper-2/50 border-rule text-ink-2 hover:border-accent/40'"
            @click="selectExecMode('auto')"
          >
            {{ t('execAuto') }}
          </button>
          <button
            class="px-4 py-2 rounded-lg text-sm font-medium transition border"
            :class="appState.execMode === 'manual' ? 'bg-accent text-accent-ink border-accent' : 'bg-paper-2/50 border-rule text-ink-2 hover:border-accent/40'"
            :disabled="!manualSupported"
            :title="!manualSupported ? t('manualUnsupported') : ''"
            @click="selectExecMode('manual')"
          >
            {{ t('execManual') }}
          </button>
        </div>
        <span class="text-xs text-muted">{{ t('execModeHint') }}</span>
      </div>

      <!-- 手动模式：暂停点多选（PRD §6.1） -->
      <div v-if="appState.execMode === 'manual' && manualSupported" class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <span class="text-xs text-muted">{{ t('pausePoints') }}:</span>
        <label v-for="p in currentPausePoints" :key="p.key" class="flex items-center gap-1.5 text-sm text-ink-2 cursor-pointer">
          <input type="checkbox" class="rounded bg-paper-2 border-rule" :checked="appState.pausePoints.includes(p.key)" @change="togglePausePoint(p.key)" />
          <span>{{ t(p.label) }}</span>
        </label>
        <span class="text-xs text-muted">{{ t('pausePointsHint') }}</span>
      </div>
      <!-- 不支持的类型提示 -->
      <div v-else-if="appState.execMode === 'manual'" class="mt-3 text-xs text-amber-400">
        {{ t('manualUnsupported') }}
      </div>
    </div>

    <!-- Task Type Tabs -->
    <div class="flex gap-2 mb-4">
      <button
        v-for="tt in taskTypes"
        :key="tt.key"
        class="ttype-btn flex-1 px-4 py-3 rounded-xl text-sm font-medium transition text-center"
        :class="appState.currentTaskType === tt.key ? 'tab-active' : 'tab-inactive'"
        @click="switchTaskType(tt.key)"
      >
        <span class="text-lg">{{ tt.icon }}</span><br /><span>{{ t(tt.label) }}</span>
      </button>
    </div>

    <!-- 官网引导 -->
    <div class="flex flex-wrap items-center gap-x-4 gap-y-1 mb-4 text-xs text-muted">
      <span class="text-muted">💡</span>
      <a href="https://video.lichuanyang.top/guides/prompt-tips" target="_blank" rel="noopener" class="hover:text-accent transition-colors">🎯 {{ t('formTipTips') }}</a>
      <span class="text-ink/10 select-none">·</span>
      <a href="https://video.lichuanyang.top/api-docs" target="_blank" rel="noopener" class="hover:text-accent transition-colors">🧠 {{ t('formTipModels') }}</a>
    </div>

    <!-- 6 种任务表单 -->
    <SimpleForm v-if="appState.currentTaskType === 'simple'" />
    <CreativeForm v-else-if="appState.currentTaskType === 'creative'" />
    <ManuscriptForm v-else-if="appState.currentTaskType === 'manuscript'" />
    <AnchorForm v-else-if="appState.currentTaskType === 'anchor'" />
    <PoetryForm v-else-if="appState.currentTaskType === 'poetry'" />
  </div>
</template>
