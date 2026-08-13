<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { t } from '@/i18n'
import { appState } from '@/store'
import { useGa } from '@/composables/useGa'
import { useProgress } from '@/composables/useProgress'
import { useToast } from '@/composables/useToast'
import * as api from '@/api'
import WatermarkToggle from '@/components/shared/WatermarkToggle.vue'

const { trackEvent } = useGa()
const { setRunning, showProgress, startPolling } = useProgress()
const { showToast } = useToast()

// Sub-mode: video / image
const subMode = ref<'video' | 'image'>('video')

// Video form
const video = reactive({
  prompt: '',
  mode: 't2v',
  duration: '5',
  resolution: '768x1152',
  seed: '',
  negative: '',
  system: '',
  refImage: null as File | null,
  refName: '',
  endImage: null as File | null,
  endName: '',
})

// Image form
const image = reactive({
  prompt: '',
  size: '1024x1024',
  negative: '',
  system: '',
  refImage: null as File | null,
  refName: '',
  imageResultVisible: false,
  imageResultSrc: '',
})

const advancedCollapsed = reactive({ video: true, image: true })
const submitting = ref(false)

function toggleCollapse(key: 'video' | 'image') {
  advancedCollapsed[key] = !advancedCollapsed[key]
}

function onRefImageChange(e: Event, target: 'video' | 'image') {
  const file = (e.target as HTMLInputElement).files?.[0] || null
  if (target === 'video') {
    video.refImage = file
    video.refName = file ? file.name : ''
  } else {
    image.refImage = file
    image.refName = file ? file.name : ''
  }
}

function onEndImageChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0] || null
  video.endImage = file
  video.endName = file ? file.name : ''
}

function parseResolution(val: string) {
  const [w, h] = val.split('x').map(Number)
  return { width: w, height: h }
}

async function submitSimple() {
  const prompt = video.prompt.trim()
  if (!prompt) {
    alert(t('enterPrompt'))
    return
  }
  submitting.value = true
  const form = new FormData()
  form.append('prompt', prompt)
  form.append('mode', video.mode)
  form.append('duration', video.duration)
  const res = parseResolution(video.resolution)
  form.append('video_width', String(res.width))
  form.append('video_height', String(res.height))
  if (video.seed) form.append('seed', video.seed)
  if (video.negative) form.append('negative_prompt', video.negative)
  if (video.system.trim()) form.append('system_prompt', video.system.trim())
  if (video.refImage) form.append('reference_image', video.refImage)
  if (video.endImage) form.append('end_frame_image', video.endImage)

  try {
    const d = await api.submitSimple(form)
    if (!d.ok) throw new Error(d.detail || t('failCreate'))
    trackEvent('create_task', {
      task_type: 'simple',
      mode: video.mode,
      duration: video.duration,
      resolution: video.resolution,
    })
    appState.currentTaskType = 'simple'
    setRunning(d.task_id)
    appState.currentDirName = d.dir_name
    await showProgress(d.task_id, d.dir_name)
    await startPolling(d.task_id)
    showToast(t('submitted'), 5000)
  } catch (e: any) {
    trackEvent('create_task_failed', { task_type: 'simple', error: (e.message || '').slice(0, 120) })
    alert(t('failCreate') + ': ' + e.message)
  } finally {
    submitting.value = false
  }
}

async function submitImage() {
  const prompt = image.prompt.trim()
  if (!prompt) {
    alert(t('enterImagePrompt'))
    return
  }
  const form = new FormData()
  form.append('prompt', prompt)
  form.append('size', image.size)
  if (image.negative) form.append('negative_prompt', image.negative)
  if (image.system.trim()) form.append('system_prompt', image.system.trim())
  if (image.refImage) form.append('reference_image', image.refImage)

  try {
    const d = await api.submitImage(form)
    if (!d.ok) throw new Error(d.detail || t('failCreate'))
    trackEvent('create_task', { task_type: 'image', size: image.size })
    image.imageResultSrc = '/api/image/' + d.task_id
    image.imageResultVisible = true
    showToast(t('imgComplete'), 5000)
  } catch (e: any) {
    trackEvent('create_task_failed', { task_type: 'image', error: (e.message || '').slice(0, 120) })
    alert(t('failCreate') + ': ' + e.message)
  }
}
</script>

<template>
  <div>
    <div class="flex items-center gap-2 mb-4 text-xs text-muted">
      <span class="text-muted">💡</span>
      <a href="https://video.lichuanyang.top/guides/prompt-examples-simple" target="_blank" rel="noopener" class="hover:text-accent transition-colors">{{ t('exampleLinkSimple') }}</a>
    </div>

    <!-- Sub-mode selector -->
    <div class="glass-card rounded-xl p-3 mb-4 flex items-center gap-3">
      <label class="text-sm text-muted whitespace-nowrap">{{ t('subModeLabel') }}</label>
      <select v-model="subMode" class="flex-1 glass-input rounded-lg px-3 py-2 text-sm text-ink">
        <option value="video">{{ t('subModeVideo') }}</option>
        <option value="image">{{ t('subModeImage') }}</option>
      </select>
    </div>

    <!-- Video sub-form -->
    <div v-if="subMode === 'video'">
      <div class="glass-card rounded-2xl p-6 mb-4">
        <h2 class="text-lg font-semibold text-accent mb-4">{{ t('simpleSettings') }}</h2>

        <div class="mb-4">
          <label class="block text-sm text-muted mb-1.5">{{ t('promptLabel') }} (prompt) <span class="text-red-400">*</span></label>
          <textarea v-model="video.prompt" rows="3" :placeholder="t('promptPlaceholder')" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm resize-y text-ink placeholder-muted"></textarea>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          <div>
            <label class="block text-sm text-muted mb-1.5">{{ t('genMode') }}</label>
            <select v-model="video.mode" class="w-full glass-input rounded-lg px-3 py-2.5 text-sm text-ink">
              <option value="t2v">{{ t('modeT2v') }}</option>
              <option value="i2v">{{ t('modeI2v') }}</option>
              <option value="keyframes">{{ t('modeKeyframesSimple') }}</option>
            </select>
          </div>
          <div>
            <label class="block text-sm text-muted mb-1.5">{{ t('duration') }}</label>
            <select v-model="video.duration" class="w-full glass-input rounded-lg px-3 py-2.5 text-sm text-ink">
              <option value="5">5s</option>
              <option value="10">10s</option>
              <option value="15">15s</option>
              <option value="18">18s</option>
              <option value="20">20s</option>
            </select>
          </div>
          <div>
            <label class="block text-sm text-muted mb-1.5">{{ t('resolution') }}</label>
            <select v-model="video.resolution" class="w-full glass-input rounded-lg px-3 py-2.5 text-sm text-ink">
              <option value="768x1152">{{ t('resPortrait') }}</option>
              <option value="1152x768">{{ t('resLandscape') }}</option>
              <option value="1024x1024">{{ t('resSquare') }}</option>
            </select>
          </div>
        </div>

        <!-- Reference Image -->
        <div v-if="video.mode !== 't2v'" class="mb-4">
          <label class="block text-sm text-muted mb-1.5">{{ t('refImageSimple') }}</label>
          <div class="flex items-center gap-4">
            <label class="cursor-pointer px-4 py-2.5 glass-input rounded-lg text-sm transition inline-block hover:border-blue-500/30">
              <span>{{ t('chooseImage') }}</span>
              <input type="file" accept="image/*" class="hidden" @change="onRefImageChange($event, 'video')" />
            </label>
            <span class="text-sm text-muted">{{ video.refName || t('notSelected') }}</span>
          </div>
        </div>

        <!-- End Frame -->
        <div v-if="video.mode === 'keyframes'" class="mb-4">
          <label class="block text-sm text-muted mb-1.5">{{ t('endFrameImage') }}</label>
          <div class="flex items-center gap-4">
            <label class="cursor-pointer px-4 py-2.5 glass-input rounded-lg text-sm transition inline-block hover:border-blue-500/30">
              <span>{{ t('chooseImage') }}</span>
              <input type="file" accept="image/*" class="hidden" @change="onEndImageChange" />
            </label>
            <span class="text-sm text-muted">{{ video.endName || t('notSelected') }}</span>
          </div>
        </div>

        <!-- Advanced -->
        <div class="border-t border-rule/40 pt-4 mt-4">
          <div class="collapse-header flex items-center justify-between" @click="toggleCollapse('video')">
            <span class="text-sm text-muted">{{ t('advancedSettings') }}</span>
            <span class="text-muted text-xs">{{ advancedCollapsed.video ? '▶' : '▼' }}</span>
          </div>
          <div v-show="!advancedCollapsed.video" class="mt-3">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="block text-sm text-muted mb-1.5">Seed ({{ t('optional') }})</label>
                <input v-model="video.seed" type="number" :placeholder="t('seedPlaceholder')" class="w-full glass-input rounded-lg px-3 py-2.5 text-sm text-ink" />
              </div>
              <div>
                <label class="block text-sm text-muted mb-1.5">Negative Prompt ({{ t('optional') }})</label>
                <input v-model="video.negative" :placeholder="t('negativePlaceholder')" class="w-full glass-input rounded-lg px-3 py-2.5 text-sm text-ink" />
              </div>
            </div>
            <div class="mt-4">
              <label class="block text-sm text-muted mb-1.5">{{ t('systemPrompt') }} ({{ t('optional') }})</label>
              <textarea v-model="video.system" rows="2" :placeholder="t('systemPromptPlaceholder')" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm resize-y text-ink placeholder-muted"></textarea>
            </div>
          </div>
        </div>
      </div>

      <WatermarkToggle />

      <button
        class="w-full py-3.5 bg-accent text-accent-ink hover:bg-accent/90 rounded-xl text-base font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed glow-btn"
        :disabled="submitting"
        @click="submitSimple"
      >
        {{ submitting ? t('submitting') : t('startGenerate') }}
      </button>
    </div>

    <!-- Image sub-form -->
    <div v-else>
      <div class="glass-card rounded-2xl p-6 mb-4">
        <h2 class="text-lg font-semibold text-accent mb-4">{{ t('imageSettings') }}</h2>

        <div class="mb-4">
          <label class="block text-sm text-muted mb-1.5">{{ t('imagePrompt') }} (prompt) <span class="text-red-400">*</span></label>
          <textarea v-model="image.prompt" rows="3" :placeholder="t('imagePromptPlaceholder')" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm resize-y text-ink placeholder-muted"></textarea>
        </div>

        <div class="mb-4">
          <label class="block text-sm text-muted mb-1.5">{{ t('imageSize') }}</label>
          <select v-model="image.size" class="w-full glass-input rounded-lg px-3 py-2.5 text-sm text-ink">
            <option value="1024x1024">{{ t('resSquare') }} (1024x1024)</option>
            <option value="768x1152">{{ t('resPortrait') }} (768x1152)</option>
            <option value="1152x768">{{ t('resLandscape') }} (1152x768)</option>
            <option value="768x1344">{{ t('resPortraitHD') }} (HD)</option>
            <option value="1344x768">{{ t('resLandscapeHD') }} (HD)</option>
            <option value="1024x1792">{{ t('resPortraitTall') }}</option>
            <option value="1792x1024">{{ t('resLandscapeWide') }}</option>
          </select>
        </div>

        <div class="mb-4">
          <label class="block text-sm text-muted mb-1.5">{{ t('refImageSimple') }}</label>
          <div class="flex items-center gap-4">
            <label class="cursor-pointer px-4 py-2.5 glass-input rounded-lg text-sm transition inline-block hover:border-blue-500/30">
              <span>{{ t('chooseImage') }}</span>
              <input type="file" accept="image/*" class="hidden" @change="onRefImageChange($event, 'image')" />
            </label>
            <span class="text-sm text-muted">{{ image.refName || t('notSelected') }}</span>
          </div>
          <p class="text-xs text-muted mt-1">{{ t('refImageHint') }}</p>
        </div>

        <div class="border-t border-rule/40 pt-4 mt-4">
          <div class="collapse-header flex items-center justify-between" @click="toggleCollapse('image')">
            <span class="text-sm text-muted">{{ t('advancedSettings') }}</span>
            <span class="text-muted text-xs">{{ advancedCollapsed.image ? '▶' : '▼' }}</span>
          </div>
          <div v-show="!advancedCollapsed.image" class="mt-3">
            <div>
              <label class="block text-sm text-muted mb-1.5">Negative Prompt ({{ t('optional') }})</label>
              <input v-model="image.negative" :placeholder="t('negativePlaceholder')" class="w-full glass-input rounded-lg px-3 py-2.5 text-sm text-ink" />
            </div>
            <div class="mt-4">
              <label class="block text-sm text-muted mb-1.5">{{ t('systemPrompt') }} ({{ t('optional') }})</label>
              <textarea v-model="image.system" rows="2" :placeholder="t('systemPromptPlaceholder')" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm resize-y text-ink placeholder-muted"></textarea>
            </div>
          </div>
        </div>
      </div>

      <button
        class="w-full py-3.5 bg-accent text-accent-ink hover:bg-accent/90 rounded-xl text-base font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed glow-btn"
        @click="submitImage"
      >
        {{ t('imgGenerate') }}
      </button>

      <div v-if="image.imageResultVisible" class="mt-4 p-4 glass-card rounded-lg">
        <p class="text-green-400 text-sm font-medium mb-2">{{ t('imgComplete') }}</p>
        <img :src="image.imageResultSrc" class="w-full rounded-lg max-h-96 object-contain" />
      </div>
    </div>
  </div>
</template>
