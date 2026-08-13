import { ref, reactive, computed } from 'vue'
import { T } from './translations'

// 支持的语言列表（与 lang-selector 选项一致）
export const LANGS: { code: string; label: string }[] = [
  { code: 'zh', label: '🇨🇳 中文' },
  { code: 'en', label: '🇺🇸 English' },
  { code: 'ru', label: '🇷🇺 Русский' },
  { code: 'ja', label: '🇯🇵 日本語' },
  { code: 'ko', label: '🇰🇷 한국어' },
  { code: 'ms', label: '🇲🇾 Bahasa Melayu' },
  { code: 'id', label: '🇮🇩 Bahasa Indonesia' },
  { code: 'de', label: '🇩🇪 Deutsch' },
  { code: 'fr', label: '🇫🇷 Français' },
  { code: 'nl', label: '🇳🇱 Nederlands' },
  { code: 'es', label: '🇪🇸 Español' },
  { code: 'pt', label: '🇵🇹 Português' },
  { code: 'it', label: '🇮🇹 Italiano' },
  { code: 'tr', label: '🇹🇷 Türkçe' },
  { code: 'vi', label: '🇻🇳 Tiếng Việt' },
  { code: 'th', label: '🇹🇭 ไทย' },
  { code: 'hi', label: '🇮🇳 हिन्दी' },
  { code: 'bn', label: '🇧🇩 বাংলা' },
  { code: 'tl', label: '🇵🇭 Tagalog' },
  { code: 'ar', label: '🇸🇦 العربية' },
  { code: 'fa', label: '🇮🇷 فارسی' },
  { code: 'ur', label: '🇵🇰 اردو' },
]

const RTL_LANGS = ['ar', 'fa', 'ur']

const currentLang = ref('zh')

function initLang(): string {
  try {
    return localStorage.getItem('lang') || 'zh'
  } catch {
    return 'zh'
  }
}

export function t(key: string): string {
  const lang = currentLang.value
  const val = (T[lang] && T[lang][key]) ?? (T['zh'] && T['zh'][key]) ?? key
  return val
}

export function applyLanguage(lang: string) {
  currentLang.value = lang || 'zh'
  try {
    localStorage.setItem('lang', currentLang.value)
  } catch {
    /* ignore */
  }
  document.documentElement.lang = currentLang.value === 'zh' ? 'zh-CN' : currentLang.value
  document.documentElement.dir = RTL_LANGS.includes(currentLang.value) ? 'rtl' : 'ltr'
}

// 转义动态文本，防止 innerHTML 注入（XSS 防护）
export function escapeHtml(s: unknown): string {
  if (s === null || s === undefined) return ''
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

export function useI18n() {
  const lang = computed(() => currentLang.value)

  function switchLang(l: string) {
    applyLanguage(l)
  }

  // 判断某值是否属于某 i18n key 的默认值集合（用于语言切换时刷新默认值）
  function isDefaultValue(value: string, i18nKey: string): boolean {
    const allDefaults = new Set(Object.values(T).map((l) => l[i18nKey]).filter(Boolean))
    return allDefaults.has(value) || value === ''
  }

  return { lang, currentLang, t, switchLang, isDefaultValue, applyLanguage }
}

// 初始化语言（模块加载后立即同步）
currentLang.value = initLang()

export { currentLang }
