<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { t } from '@/i18n'
import { appState } from '@/store'
import { useGa } from '@/composables/useGa'
import { useNavigation } from '@/composables/useNavigation'
import { useToast } from '@/composables/useToast'
import { useVoice } from '@/composables/useVoice'
import * as api from '@/api'
import WatermarkToggle from '@/components/shared/WatermarkToggle.vue'
import SubtitleConfig from '@/components/shared/SubtitleConfig.vue'

const { trackEvent } = useGa()
const { goProgress } = useNavigation()
const { showToast } = useToast()
const { voiceSelections } = useVoice()

const subtitleRef = ref<InstanceType<typeof SubtitleConfig>>()

const form = reactive({
  scriptText: '',
  visualStyle: 'cinematic photorealistic',
  maxScenes: 0,
  maxShots: 0,
  resolution: '1920x1080',
})

const charCount = computed(() => form.scriptText.length)
const submitting = ref(false)

function parseResolution(val: string) {
  const [w, h] = val.split('x').map(Number)
  return { width: w, height: h }
}

async function submitMovie() {
  if (!form.scriptText.trim()) {
    alert(t('enterText'))
    return
  }

  submitting.value = true
  const fd = new FormData()
  fd.append('script_text', form.scriptText.trim())
  fd.append('visual_style_preset', form.visualStyle.trim())
  fd.append('max_scenes', String(form.maxScenes))
  fd.append('max_shots', String(form.maxShots))

  const res = parseResolution(form.resolution)
  fd.append('video_width', String(res.width))
  fd.append('video_height', String(res.height))

  // Voice (dialogue TTS)
  fd.append('voice_role', voiceSelections.a)
  fd.append('voice_speed', '1.0')

  // Subtitle
  const sc = subtitleRef.value
  if (sc) {
    fd.append('enable_subtitle', String(sc.subtitleEnabled))
    fd.append('enable_narration', String(sc.audioEnabled))
    fd.append('subtitle_style_mode', sc.styleMode)
    fd.append('subtitle_font', sc.style.font)
    fd.append('subtitle_color', sc.style.color)
    fd.append('subtitle_fontsize', String(sc.style.fontsize))
    fd.append('subtitle_position', sc.style.position)
    fd.append('subtitle_stroke_color', sc.style.stroke_color)
    fd.append('subtitle_stroke_width', String(sc.style.stroke_width))
    fd.append('subtitle_bg_color', sc.style.bg_color)
  }

  try {
    const d = await api.submitMovie(fd)
    if (!d.ok) throw new Error(d.detail || t('failCreate'))
    trackEvent('create_task', {
      task_type: 'movie',
      resolution: form.resolution,
    })
    appState.currentTaskType = 'movie'
    appState.currentDirName = d.dir_name
    goProgress(d.task_id, 'create')
    showToast(t('submitted'), 5000)
  } catch (e: any) {
    trackEvent('create_task_failed', { task_type: 'movie', error: (e.message || '').slice(0, 120) })
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
      <span>{{ t('movieHint') }}</span>
    </div>

    <div class="glass-card rounded-2xl p-6 mb-4">
      <h2 class="text-lg font-semibold text-accent mb-4">{{ t('movieSettings') }}</h2>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('movieScript') }} <span class="text-red-400">*</span></label>
        <textarea v-model="form.scriptText" rows="10" :placeholder="t('movieScriptPlaceholder')" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm resize-y text-ink placeholder-muted font-mono"></textarea>
        <p class="text-xs text-muted mt-1">{{ t('movieCharCount') }}: {{ charCount }}</p>
      </div>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('movieStyle') }}</label>
        <input v-model="form.visualStyle" type="text" :placeholder="t('movieStylePlaceholder')" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm text-ink placeholder-muted" />
        <p class="text-xs text-muted mt-1">{{ t('movieBestModelNote') }}</p>
      </div>

      <div class="grid grid-cols-2 gap-4 mb-4">
        <div>
          <label class="block text-sm text-muted mb-1.5">{{ t('movieMaxScenes') }}</label>
          <input v-model.number="form.maxScenes" type="number" min="0" max="50" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm text-ink" />
        </div>
        <div>
          <label class="block text-sm text-muted mb-1.5">{{ t('movieMaxShots') }}</label>
          <input v-model.number="form.maxShots" type="number" min="0" max="200" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm text-ink" />
        </div>
      </div>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('movieResolution') }}</label>
        <select v-model="form.resolution" class="w-full glass-input rounded-lg px-3 py-2.5 text-sm text-ink">
          <option value="1920x1080">{{ t('resLandscape') }}</option>
          <option value="1080x1920">{{ t('resPortrait') }}</option>
          <option value="1024x1024">{{ t('resSquare') }}</option>
        </select>
        <p class="text-xs text-muted mt-1">{{ t('movieOptional') }}</p>
      </div>
    </div>

    <SubtitleConfig ref="subtitleRef" task="a" :with-style="true" />

    <WatermarkToggle />

    <button
      class="w-full py-3.5 bg-accent text-accent-ink hover:bg-accent/90 rounded-xl text-base font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed glow-btn"
      :disabled="submitting"
      @click="submitMovie"
    >
      {{ submitting ? t('submitting') : t('movieStartGenerate') }}
    </button>
  </div>
</template>
