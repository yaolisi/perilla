import DOMPurify from 'dompurify'

const DEFAULT_ALLOWED_URI_REGEXP = /^(?:(?:https?|mailto|tel):|\/|#)/i

export function sanitizeHtml(input: string): string {
  return DOMPurify.sanitize(input || '', {
    USE_PROFILES: { html: true, svg: true, svgFilters: false, mathMl: false },
    ALLOWED_URI_REGEXP: DEFAULT_ALLOWED_URI_REGEXP,
    FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed'],
    FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover'],
  })
}

export function getCookie(name: string): string | null {
  const encodedName = `${encodeURIComponent(name)}=`
  const parts = document.cookie.split(';')
  for (const rawPart of parts) {
    const part = rawPart.trim()
    if (part.startsWith(encodedName)) {
      const value = part.slice(encodedName.length)
      return decodeURIComponent(value)
    }
  }
  return null
}
