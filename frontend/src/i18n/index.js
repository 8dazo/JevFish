import { createI18n } from 'vue-i18n'
import languages from '../../../locales/languages.json'

const localeFiles = import.meta.glob('../../../locales/!(languages).json', { eager: true })

const rebrandCopy = (value) => {
  if (typeof value === 'string') {
    return value
      .replaceAll('MiroFish', 'JevFish')
      .replaceAll('MIROFISH', 'JEVFISH')
      .replaceAll('Mirofish', 'JevFish')
  }
  if (Array.isArray(value)) return value.map(rebrandCopy)
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, nested]) => [key, rebrandCopy(nested)])
    )
  }
  return value
}

const messages = {}
const availableLocales = []

for (const path in localeFiles) {
  const key = path.match(/\/([^/]+)\.json$/)[1]
  if (languages[key]) {
    messages[key] = rebrandCopy(localeFiles[path].default)
    availableLocales.push({ key, label: languages[key].label })
  }
}

const savedLocale = localStorage.getItem('locale') || 'zh'

const i18n = createI18n({
  legacy: false,
  locale: savedLocale,
  fallbackLocale: 'zh',
  messages
})

export { availableLocales }
export default i18n
