import { ref } from 'vue'

const visible = ref(false)
const message = ref('')
let timer: ReturnType<typeof setTimeout> | null = null

function showToast(msg: string, duration = 2500) {
  message.value = msg
  visible.value = true
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => {
    visible.value = false
  }, duration)
}

export function useToast() {
  return { visible, message, showToast }
}
