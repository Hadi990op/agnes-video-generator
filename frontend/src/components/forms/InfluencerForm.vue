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
  characterName: '',
  characterDescription: '',
  characterImage: null as File | null,
  characterImageName: '',
  script: '',
  sceneCount: 5,
  resolution: '768x1152',
  seed: '' as string,
})

const charCount = computed(() => form.script.length)
const submitting = ref(false)
const estimatedDuration = computed(() => form.sceneCount * 5)

function parseResolution(val: string) {
  const [w, h] = val.split('x').map(Number)
  return { width: w, height: h }
}

function onCharacterImageChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0] || null
  form.characterImage = file
  form.characterImageName = file ? file.name : ''
}

async function submitInfluencer() {
  if (!form.characterName.trim()) {
    alert(t('influencerNameRequired'))
    return
  }
  if (!form.script.trim()) {
    alert(t('enterText'))
    return
  }

  submitting.value = true
  const fd = new FormData()
  fd.append('character_name', form.characterName.trim())
  fd.append('character_description', form.characterDescription.trim())
  fd.append('script_text', form.script.trim())
  fd.append('scene_count', String(form.sceneCount))

  const res = parseResolution(form.resolution)
  fd.append('video_width', String(res.width))
  fd.append('video_height', String(res.height))

  if (form.characterImage) fd.append('character_image', form.characterImage)
  if (form.seed) fd.append('character_seed', form.seed)

  // Voice
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
    const d = await api.submitInfluencer(fd)
    if (!d.ok) throw new Error(d.detail || t('failCreate'))
    trackEvent('create_task', {
      task_type: 'influencer',
      scene_count: form.sceneCount,
      resolution: form.resolution,
    })
    appState.currentTaskType = 'influencer'
    appState.currentDirName = d.dir_name
    goProgress(d.task_id, 'create')
    showToast(t('submitted'), 5000)
  } catch (e: any) {
    trackEvent('create_task_failed', { task_type: 'influencer', error: (e.message || '').slice(0, 120) })
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
      <span>{{ t('influencerHint') }}</span>
    </div>

    <!-- Character Setup -->
    <div class="glass-card rounded-2xl p-6 mb-4">
      <h2 class="text-lg font-semibold text-accent mb-4">{{ t('influencerCharacter') }}</h2>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('influencerName') }} <span class="text-red-400">*</span></label>
        <input v-model="form.characterName" type="text" :placeholder="t('influencerNamePlaceholder')" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm text-ink placeholder-muted" />
      </div>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('influencerDescription') }}</label>
        <textarea v-model="form.characterDescription" rows="3" :placeholder="t('influencerDescPlaceholder')" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm resize-y text-ink placeholder-muted"></textarea>
        <p class="text-xs text-muted mt-1">{{ t('influencerDescHint') }}</p>
      </div>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('influencerRefImage') }}</label>
        <div class="flex items-center gap-4">
          <label class="cursor-pointer px-4 py-2.5 glass-input rounded-lg text-sm transition inline-block hover:border-blue-500/30">
            <span>{{ t('chooseImage') }}</span>
            <input type="file" accept="image/*" class="hidden" @change="onCharacterImageChange" />
          </label>
          <span class="text-sm text-muted">{{ form.characterImageName || t('notSelected') }}</span>
        </div>
        <p class="text-xs text-muted mt-1">{{ t('influencerRefImageHint') }}</p>
      </div>
    </div>

    <!-- Script -->
    <div class="glass-card rounded-2xl p-6 mb-4">
      <h2 class="text-lg font-semibold text-accent mb-4">{{ t('influencerScript') }}</h2>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('scriptText') }} <span class="text-red-400">*</span></label>
        <textarea v-model="form.script" rows="8" :placeholder="t('influencerScriptPlaceholder')" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm resize-y text-ink placeholder-muted font-mono"></textarea>
        <p class="text-xs text-muted mt-1">{{ t('charCount') }}: {{ charCount }}</p>
      </div>

      <div class="grid grid-cols-2 gap-4 mb-4">
        <div>
          <label class="block text-sm text-muted mb-1.5">{{ t('influencerSceneCount') }}</label>
          <input v-model.number="form.sceneCount" type="number" min="2" max="10" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm text-ink" />
          <p class="text-xs text-muted mt-1">~{{ estimatedDuration }}s {{ t('influencerEstimated') }}</p>
        </div>
        <div>
          <label class="block text-sm text-muted mb-1.5">{{ t('resolution') }}</label>
          <select v-model="form.resolution" class="w-full glass-input rounded-lg px-3 py-2.5 text-sm text-ink">
            <option value="768x1152">{{ t('resPortrait') }}</option>
            <option value="1152x768">{{ t('resLandscape') }}</option>
            <option value="1024x1024">{{ t('resSquare') }}</option>
          </select>
        </div>
      </div>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('influencerSeed') }} ({{ t('optional') }})</label>
        <input v-model="form.seed" type="number" :placeholder="t('influencerSeedPlaceholder')" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm text-ink placeholder-muted" />
        <p class="text-xs text-muted mt-1">{{ t('influencerSeedHint') }}</p>
      </div>
    </div>

    <!-- Audio & Subtitle -->
    <SubtitleConfig ref="subtitleRef" task="a" :with-style="true" />

    <WatermarkToggle />

    <button
      class="w-full py-3.5 bg-accent text-accent-ink hover:bg-accent/90 rounded-xl text-base font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed glow-btn"
      :disabled="submitting"
      @click="submitInfluencer"
    >
      {{ submitting ? t('submitting') : t('influencerStartGenerate') }}
    </button>
  </div>
</template>
