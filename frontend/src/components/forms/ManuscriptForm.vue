<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { t } from '@/i18n'
import { appState } from '@/store'
import { useGa } from '@/composables/useGa'
import { useProgress } from '@/composables/useProgress'
import { useToast } from '@/composables/useToast'
import { useVoice } from '@/composables/useVoice'
import * as api from '@/api'
import WatermarkToggle from '@/components/shared/WatermarkToggle.vue'
import SubtitleConfig from '@/components/shared/SubtitleConfig.vue'

const { trackEvent } = useGa()
const { setRunning, showProgress, startPolling } = useProgress()
const { showToast } = useToast()
const { voiceSelections } = useVoice()

const subtitleRef = ref<InstanceType<typeof SubtitleConfig>>()

const form = reactive({
  name: '',
  text: '',
  resolution: '768x1152',
})

const charCount = computed(() => form.text.length)
const submitting = ref(false)

function parseResolution(val: string) {
  const [w, h] = val.split('x').map(Number)
  return { width: w, height: h }
}

async function submitManuscript() {
  const text = form.text.trim()
  if (!text) {
    alert(t('enterText'))
    return
  }
  submitting.value = true
  const fd = new FormData()
  fd.append('manuscript_text', text)
  fd.append('creative_name', form.name.trim())
  const res = parseResolution(form.resolution)
  fd.append('video_width', String(res.width))
  fd.append('video_height', String(res.height))

  const sc = subtitleRef.value
  if (sc) {
    fd.append('audio_enabled', String(sc.audioEnabled))
    fd.append('audio_voice', voiceSelections.m)
    fd.append('audio_lang', 'zh')
    fd.append('audio_rate', sc.rate)
    fd.append('subtitle_enabled', String(sc.subtitleEnabled))
    fd.append('subtitle_style_mode', sc.styleMode)
    fd.append('subtitle_style_hints', sc.style.hints)
    fd.append('subtitle_font', sc.style.font)
    fd.append('subtitle_color', sc.style.color)
    fd.append('subtitle_fontsize', String(sc.style.fontsize))
    fd.append('subtitle_position', sc.style.position)
    fd.append('subtitle_stroke_color', sc.style.stroke_color)
    fd.append('subtitle_stroke_width', String(sc.style.stroke_width))
    fd.append('subtitle_bg_color', sc.style.bg_color)
  }

  try {
    const d = await api.submitManuscript(fd)
    if (!d.ok) throw new Error(d.detail || t('failCreate'))
    trackEvent('create_task', {
      task_type: 'manuscript',
      resolution: form.resolution,
      text_len: text.length,
      audio: sc?.audioEnabled ? 'on' : 'off',
      subtitle: sc?.subtitleEnabled ? 'on' : 'off',
    })
    appState.currentTaskType = 'manuscript'
    setRunning(d.task_id)
    appState.currentDirName = d.dir_name
    await showProgress(d.task_id, d.dir_name)
    await startPolling(d.task_id)
    showToast(t('submitted'), 5000)
  } catch (e: any) {
    trackEvent('create_task_failed', { task_type: 'manuscript', error: (e.message || '').slice(0, 120) })
    alert(t('failCreate') + ': ' + e.message)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div>
    <div class="flex items-center gap-2 mb-4 text-xs text-muted">
      <span class="text-muted">💡</span>
      <a href="https://video.lichuanyang.top/guides/prompt-examples-manuscript" target="_blank" rel="noopener" class="hover:text-accent transition-colors">{{ t('exampleLinkManuscript') }}</a>
    </div>

    <div class="glass-card rounded-2xl p-6 mb-4">
      <h2 class="text-lg font-semibold text-accent mb-4">{{ t('manuscriptSettings') }}</h2>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('taskName') }}</label>
        <input v-model="form.name" :placeholder="t('taskNamePlaceholder')" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm text-ink placeholder-muted" />
      </div>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('manuscriptText') }} <span class="text-red-400">*</span></label>
        <textarea v-model="form.text" rows="10" :placeholder="t('manuscriptPlaceholder')" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm resize-y text-ink placeholder-muted font-mono"></textarea>
        <p class="text-xs text-muted mt-1">{{ t('charCount') }}: {{ charCount }}</p>
      </div>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('resolution') }}</label>
        <select v-model="form.resolution" class="w-full glass-input rounded-lg px-3 py-2.5 text-sm text-ink">
          <option value="768x1152">{{ t('resPortrait') }}</option>
          <option value="1152x768">{{ t('resLandscape') }}</option>
          <option value="1024x1024">{{ t('resSquare') }}</option>
        </select>
      </div>
    </div>

    <SubtitleConfig ref="subtitleRef" task="m" :with-style="true" />

    <WatermarkToggle />

    <button
      class="w-full py-3.5 bg-accent text-accent-ink hover:bg-accent/90 rounded-xl text-base font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed glow-btn"
      :disabled="submitting"
      @click="submitManuscript"
    >
      {{ submitting ? t('submitting') : t('startGenerate') }}
    </button>
  </div>
</template>
