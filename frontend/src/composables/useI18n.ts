import { ref } from 'vue'
import zhMessages from '@/locales/zh-CN.json'
import enMessages from '@/locales/en.json'

const locale = ref(localStorage.getItem('tg-assistant-locale') || 'zh')

const messages: Record<string, Record<string, string>> = {
  zh: zhMessages,
  en: enMessages,
}

export function useI18n() {
  const toggleLanguage = () => {
    locale.value = locale.value === 'zh' ? 'en' : 'zh'
    localStorage.setItem('tg-assistant-locale', locale.value)
  }

  function t(key: string): string {
    return messages[locale.value]?.[key] || messages['zh']?.[key] || key
  }

  return { locale, toggleLanguage, t }
}
