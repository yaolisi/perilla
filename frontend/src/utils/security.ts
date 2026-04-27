import DOMPurify from 'dompurify'

const DEFAULT_ALLOWED_URI_REGEXP = /^(?:(?:https?|mailto|tel):|\/|#)/i

export function sanitizeHtml(input: string): string {
  return DOMPurify.sanitize(input || '', {
    USE_PROFILES: { html: true, svg: false, svgFilters: false, mathMl: false },
    ALLOWED_URI_REGEXP: DEFAULT_ALLOWED_URI_REGEXP,
    FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed'],
    FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover'],
  })
}

export function sanitizeMermaidSvg(input: string): string {
  return DOMPurify.sanitize(input || '', {
    USE_PROFILES: { html: false, svg: true, svgFilters: false, mathMl: false },
    ALLOWED_URI_REGEXP: DEFAULT_ALLOWED_URI_REGEXP,
    // Mermaid SVG 仅保留核心结构标签
    ALLOWED_TAGS: [
      'svg', 'g', 'path', 'line', 'polyline', 'polygon', 'rect', 'circle', 'ellipse',
      'text', 'tspan', 'defs', 'marker', 'style', 'title', 'desc', 'foreignObject',
    ],
    ALLOWED_ATTR: [
      'id', 'class', 'style', 'viewBox', 'width', 'height', 'x', 'y', 'x1', 'x2', 'y1', 'y2',
      'cx', 'cy', 'r', 'rx', 'ry', 'd', 'points', 'transform', 'fill', 'stroke', 'stroke-width',
      'stroke-linecap', 'stroke-linejoin', 'stroke-dasharray', 'opacity', 'font-size', 'font-family',
      'font-weight', 'text-anchor', 'dominant-baseline', 'marker-end', 'marker-start', 'href',
      'xmlns', 'xmlns:xlink', 'preserveAspectRatio', 'aria-hidden', 'role',
    ],
    FORBID_TAGS: ['script', 'iframe', 'object', 'embed'],
    FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover'],
  })
}

export function getCookie(name: string): string | null {
  const parts = document.cookie.split(';')
  for (const rawPart of parts) {
    const part = rawPart.trim()
    if (!part) continue
    const eq = part.indexOf('=')
    const key = eq === -1 ? part : part.slice(0, eq).trim()
    // 按首个 = 拆分键值，精确匹配 cookie 名（避免 csrf_token 撞上 csrf_token_v2）
    if (key !== name) continue
    const rawValue = eq === -1 ? '' : part.slice(eq + 1)
    try {
      return decodeURIComponent(rawValue)
    } catch {
      return rawValue
    }
  }
  return null
}
