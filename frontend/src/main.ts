import { createApp } from 'vue'
import App from './App.vue'
import './style.css'
import { applyLanguage, currentLang } from './i18n'
import { useTheme } from './composables/useTheme'
import { useGa } from './composables/useGa'

// 初始化语言
applyLanguage(currentLang.value)

// 初始化主题
const { themeApply, themeStored, initThemeListener } = useTheme()
themeApply(themeStored())
initThemeListener()

// 初始化 GA 与全局错误捕获
const { initGA, initErrorListeners } = useGa()
initGA()
initErrorListeners()

createApp(App).mount('#app')
