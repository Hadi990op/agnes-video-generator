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
  prompt: '',
  refImage: null as File | null,
  refName: '',
  script: '',
  resolution: '768x1344',
  audioSource: 'post_stitch' as 'post_stitch' | 'model',
})

const charCount = computed(() => form.script.length)
const submitting = ref(false)

function parseResolution(val: string) {
  const [w, h] = val.split('x').map(Number)
  return { width: w, height: h }
}

function onRefImageChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0] || null
  form.refImage = file
  form.refName = file ? file.name : ''
}

async function submitAnchor() {
  const script = form.script.trim()
  if (!script) {
    alert(t('enterText'))
    return
  }
  submitting.value = true
  const fd = new FormData()
  fd.append('script_text', script)
  const prompt = form.prompt.trim()
  if (prompt) fd.append('anchor_prompt', prompt)
  const res = parseResolution(form.resolution)
  fd.append('video_width', String(res.width))
  fd.append('video_height', String(res.height))
  if (form.refImage) fd.append('anchor_reference_image', form.refImage)
  fd.append('audio_source', form.audioSource)

  const sc = subtitleRef.value
  if (sc) {
    fd.append('audio_enabled', String(form.audioSource === 'model' ? false : sc.audioEnabled))
    fd.append('audio_voice', voiceSelections.a)
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

  // v6.0 手动模式：执行模式 + 暂停点
  fd.append('execution_mode', appState.execMode)
  fd.append('pause_points', JSON.stringify(appState.execMode === 'manual' ? appState.pausePoints : []))

  try {
    const d = await api.submitAnchor(fd)
    if (!d.ok) throw new Error(d.detail || t('failCreate'))
    trackEvent('create_task', {
      task_type: 'anchor',
      resolution: form.resolution,
      audio_source: form.audioSource,
      audio: form.audioSource === 'model' ? 'off' : sc?.audioEnabled ? 'on' : 'off',
      subtitle: sc?.subtitleEnabled ? 'on' : 'off',
    })
    appState.currentTaskType = 'anchor'
    setRunning(d.task_id)
    appState.currentDirName = d.dir_name
    await showProgress(d.task_id, d.dir_name)
    await startPolling(d.task_id)
    showToast(t('submitted'), 5000)
  } catch (e: any) {
    trackEvent('create_task_failed', { task_type: 'anchor', error: (e.message || '').slice(0, 120) })
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
      <a href="https://video.lichuanyang.top/guides/prompt-examples-anchor" target="_blank" rel="noopener" class="hover:text-accent transition-colors">{{ t('exampleLinkAnchor') }}</a>
    </div>

    <div class="glass-card rounded-2xl p-6 mb-4">
      <h2 class="text-lg font-semibold text-accent mb-4">{{ t('anchorSettings') }}</h2>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('anchorPrompt') }}</label>
        <textarea v-model="form.prompt" rows="3" :placeholder="t('anchorPromptPlaceholder')" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm resize-y text-ink placeholder-muted"></textarea>
      </div>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('anchorRefImage') }}</label>
        <div class="flex items-center gap-4">
          <label class="cursor-pointer px-4 py-2.5 glass-input rounded-lg text-sm transition inline-block hover:border-blue-500/30">
            <span>{{ t('chooseImage') }}</span>
            <input type="file" accept="image/*" class="hidden" @change="onRefImageChange" />
          </label>
          <span class="text-sm text-muted">{{ form.refName || t('notSelected') }}</span>
        </div>
        <p class="text-xs text-muted mt-1">{{ t('anchorRefImageHint') }}</p>
      </div>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('scriptText') }} <span class="text-red-400">*</span></label>
        <textarea v-model="form.script" rows="8" :placeholder="t('scriptTextPlaceholder')" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm resize-y text-ink placeholder-muted font-mono"></textarea>
        <p class="text-xs text-muted mt-1">{{ t('charCount') }}: {{ charCount }}</p>
      </div>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('resolution') }}</label>
        <select v-model="form.resolution" class="w-full glass-input rounded-lg px-3 py-2.5 text-sm text-ink">
          <option value="768x1344">{{ t('resPortraitHD') }}</option>
          <option value="1152x768">{{ t('resLandscape') }}</option>
          <option value="1024x1024">{{ t('resSquare') }}</option>
        </select>
      </div>
    </div>

    <!-- Audio Source (Anchor only) -->
    <div class="glass-card rounded-2xl p-6 mb-4">
      <div class="mb-4 p-3 bg-paper-2/50 rounded-lg border border-rule">
        <label class="block text-sm text-muted mb-2">{{ t('audioSource') }}</label>
        <div class="flex flex-col gap-2">
          <label class="flex items-start gap-3 cursor-pointer group">
            <input v-model="form.audioSource" type="radio" name="a_audio_source" value="post_stitch" class="mt-0.5 accent-blue-500" />
            <div>
              <span class="text-sm text-ink-2 group-hover:text-ink transition">{{ t('audioPostStitch') }}</span>
              <p class="text-xs text-muted mt-0.5">{{ t('audioPostStitchDesc') }}</p>
            </div>
          </label>
          <label class="flex items-start gap-3 cursor-pointer group">
            <input v-model="form.audioSource" type="radio" name="a_audio_source" value="model" class="mt-0.5 accent-blue-500" />
            <div>
              <span class="text-sm text-ink-2 group-hover:text-ink transition">{{ t('audioModel') }}</span>
              <p class="text-xs text-muted mt-0.5">{{ t('audioModelDesc') }}</p>
            </div>
          </label>
        </div>
      </div>
    </div>

    <!-- Audio & Subtitle（model 模式禁用音频） -->
    <div :class="{ 'opacity-40 pointer-events-none': form.audioSource === 'model' }">
      <SubtitleConfig ref="subtitleRef" task="a" :with-style="true" />
    </div>

    <WatermarkToggle />

    <button
      class="w-full py-3.5 bg-accent text-accent-ink hover:bg-accent/90 rounded-xl text-base font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed glow-btn"
      :disabled="submitting"
      @click="submitAnchor"
    >
      {{ submitting ? t('submitting') : t('startGenerate') }}
    </button>
  </div>
</template>
