<script setup lang="ts">
import { ref, reactive } from 'vue'
import { t } from '@/i18n'
import VoiceSelector from './VoiceSelector.vue'

// 共享字幕样式配置（创意/稿件/数字人共用；诗词仅开关）
const props = defineProps<{
  task: string // c/m/a/p
  withStyle?: boolean // 诗词为 false（仅开关）
  defaultFontsize?: number
}>()

const audioEnabled = ref(true)
const subtitleEnabled = ref(true)
const rate = ref('+0%')

const styleMode = ref<'fixed' | 'llm'>('fixed')
const style = reactive({
  font: 'STHeitiMedium.ttc',
  color: 'white',
  fontsize: props.defaultFontsize ?? 48,
  position: 'bottom',
  stroke_color: 'black',
  stroke_width: 2,
  bg_color: 'black@0.5',
  hints: '',
})

const collapsed = reactive({ audio: true, subtitle: true })

function toggleCollapse(key: 'audio' | 'subtitle') {
  collapsed[key] = !collapsed[key]
}

// 暴露表单数据给父组件
defineExpose({
  audioEnabled,
  subtitleEnabled,
  rate,
  styleMode,
  style,
})
</script>

<template>
  <!-- Audio Config -->
  <div class="glass-card rounded-2xl p-6 mb-4">
    <div class="collapse-header flex items-center justify-between" @click="toggleCollapse('audio')">
      <h2 class="text-lg font-semibold text-accent">{{ t('audioConfig') }}</h2>
      <span class="text-muted text-xs">{{ collapsed.audio ? '▶' : '▼' }}</span>
    </div>
    <div v-show="!collapsed.audio" class="mt-4">
      <div class="flex items-center gap-3 mb-4">
        <label class="flex items-center gap-2 text-sm text-ink-2 cursor-pointer">
          <input v-model="audioEnabled" type="checkbox" class="rounded bg-paper-2 border-rule" />
          <span>{{ t('enableNarration') }}</span>
        </label>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <div>
          <label class="block text-sm text-muted mb-1.5">{{ t('voiceRole') }}</label>
          <VoiceSelector :task="task" />
        </div>
        <div>
          <label class="block text-sm text-muted mb-1.5">{{ t('speechRate') }}</label>
          <select v-model="rate" class="w-full glass-input rounded-lg px-3 py-2.5 text-sm text-ink">
            <option value="-30%">{{ t('rateSlow') }}</option>
            <option value="-15%">-15%</option>
            <option value="+0%">{{ t('rateNormal') }}</option>
            <option value="+15%">+15%</option>
            <option value="+30%">{{ t('rateFast') }}</option>
          </select>
        </div>
      </div>
    </div>
  </div>

  <!-- Subtitle Config -->
  <div class="glass-card rounded-2xl p-6 mb-4">
    <div class="collapse-header flex items-center justify-between" @click="toggleCollapse('subtitle')">
      <h2 class="text-lg font-semibold text-accent">{{ t('subtitleConfig') }}</h2>
      <span class="text-muted text-xs">{{ collapsed.subtitle ? '▶' : '▼' }}</span>
    </div>
    <div v-show="!collapsed.subtitle" class="mt-4">
      <div class="flex items-center gap-3 mb-4">
        <label class="flex items-center gap-2 text-sm text-ink-2 cursor-pointer">
          <input v-model="subtitleEnabled" type="checkbox" class="rounded bg-paper-2 border-rule" />
          <span>{{ t('enableSubtitle') }}</span>
        </label>
      </div>

      <template v-if="withStyle">
        <div class="border-t border-rule/40 pt-4">
          <div class="mb-4">
            <label class="block text-sm text-muted mb-1.5">{{ t('subStyleMode') }}</label>
            <select v-model="styleMode" class="w-full glass-input rounded-lg px-3 py-2 text-sm text-ink">
              <option value="fixed">{{ t('subStyleFixed') }}</option>
              <option value="llm">{{ t('subStyleLLM') }}</option>
            </select>
          </div>

          <div v-if="styleMode === 'fixed'">
            <p class="text-sm text-muted mb-3">{{ t('subtitleStyle') }}</p>
            <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div>
                <label class="block text-xs text-muted mb-1">{{ t('subFont') }}</label>
                <input v-model="style.font" class="w-full glass-input rounded px-2 py-1.5 text-xs text-ink" />
              </div>
              <div>
                <label class="block text-xs text-muted mb-1">{{ t('subColor') }}</label>
                <input v-model="style.color" class="w-full glass-input rounded px-2 py-1.5 text-xs text-ink" />
              </div>
              <div>
                <label class="block text-xs text-muted mb-1">{{ t('subSize') }}</label>
                <input v-model.number="style.fontsize" type="number" class="w-full glass-input rounded px-2 py-1.5 text-xs text-ink" />
              </div>
              <div>
                <label class="block text-xs text-muted mb-1">{{ t('subPosition') }}</label>
                <select v-model="style.position" class="w-full glass-input rounded px-2 py-1.5 text-xs text-ink">
                  <option value="bottom">{{ t('posBottom') }}</option>
                  <option value="top">{{ t('posTop') }}</option>
                </select>
              </div>
            </div>
            <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
              <div>
                <label class="block text-xs text-muted mb-1">{{ t('subStrokeColor') }}</label>
                <input v-model="style.stroke_color" class="w-full glass-input rounded px-2 py-1.5 text-xs text-ink" />
              </div>
              <div>
                <label class="block text-xs text-muted mb-1">{{ t('subStrokeWidth') }}</label>
                <input v-model.number="style.stroke_width" type="number" class="w-full glass-input rounded px-2 py-1.5 text-xs text-ink" />
              </div>
              <div>
                <label class="block text-xs text-muted mb-1">{{ t('subBgColor') }}</label>
                <input v-model="style.bg_color" class="w-full glass-input rounded px-2 py-1.5 text-xs text-ink" />
              </div>
            </div>
          </div>

          <div v-else>
            <label class="block text-sm text-muted mb-1.5">{{ t('subStyleHints') }}</label>
            <textarea v-model="style.hints" rows="3" class="w-full glass-input rounded-lg px-3 py-2 text-sm text-ink placeholder-muted" :placeholder="t('subStyleHintsPlaceholder')"></textarea>
            <p class="text-xs text-muted mt-1">{{ t('subStyleHintsHint') }}</p>
          </div>
        </div>
      </template>
      <p v-else class="text-xs text-muted">{{ t('poetrySubtitleFixed') }}</p>
    </div>
  </div>
</template>
