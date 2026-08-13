// GA4 埋点（固定 Measurement ID，统一收集用户操作数据）
const GA_MEASUREMENT_ID = 'G-RQW2189QSK'
let gaEnabled = false

function initGA() {
  if (gaEnabled) return
  gaEnabled = true
  try {
    window.dataLayer = window.dataLayer || []
    window.gtag = function (...args: unknown[]) {
      window.dataLayer!.push(args)
    }
    const s = document.createElement('script')
    s.async = true
    s.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(GA_MEASUREMENT_ID)
    document.head.appendChild(s)
    window.gtag('js', new Date())
    window.gtag('config', GA_MEASUREMENT_ID)
  } catch (e) {
    console.warn('GA init failed:', e)
    gaEnabled = false
  }
}

// 统一事件上报
function trackEvent(name: string, params?: Record<string, unknown>) {
  if (!gaEnabled || typeof window.gtag !== 'function') return
  try {
    window.gtag('event', name, params || {})
  } catch {
    /* 静默 */
  }
}

// 任务结果去重上报
const trackedTaskResults: Record<string, string> = {}
function trackTaskResultOnce(name: string, taskId: string, params?: Record<string, unknown>) {
  if (trackedTaskResults[taskId] === name) return
  trackedTaskResults[taskId] = name
  trackEvent(name, params || {})
}

// 异常去重上报
let lastErrSig = ''
let lastErrTime = 0
function reportException(description: string, fatal?: boolean) {
  const now = Date.now()
  if (description === lastErrSig && now - lastErrTime < 10000) return
  lastErrSig = description
  lastErrTime = now
  trackEvent('exception', {
    description: (description || '').slice(0, 500),
    fatal: fatal ? '1' : '0',
  })
}

// 全局错误捕获
function initErrorListeners() {
  window.addEventListener('error', (e) => {
    reportException((e.message || 'Unknown error') + ' @ ' + (e.filename || 'inline') + ':' + (e.lineno || 0), true)
  })
  window.addEventListener('unhandledrejection', (e) => {
    let msg = ''
    const r = e.reason
    if (r instanceof Error) msg = r.message
    else if (r != null) msg = String(r)
    reportException('Unhandled promise rejection: ' + (msg || 'unknown'), false)
  })
}

export function useGa() {
  return { initGA, trackEvent, trackTaskResultOnce, reportException, initErrorListeners }
}

declare global {
  interface Window {
    dataLayer?: unknown[]
    gtag?: (...args: unknown[]) => void
  }
}
