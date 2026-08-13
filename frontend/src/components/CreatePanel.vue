<script setup lang="ts">
import { ref } from 'vue'
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

function switchTaskType(type: string) {
  trackEvent('ui_action', { action: 'switch_task_type', type })
  appState.currentTaskType = type
}
</script>

<template>
  <div>
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
