import MarkdownIt from 'markdown-it'
// @ts-ignore
import mk from 'markdown-it-katex'
import hljs from 'highlight.js'
// @ts-ignore
import highlightjs from 'markdown-it-highlightjs'
import { sanitizeHtml } from '@/utils/security'
import 'highlight.js/styles/github-dark.css'
import 'katex/dist/katex.min.css'

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  breaks: true,
})
  .use(mk)
  .use(highlightjs, { hljs })

// 配置链接渲染器，让所有链接在新标签页打开
const defaultLinkOpen = md.renderer.rules.link_open || function(tokens, idx, options, _env, self) {
  return self.renderToken(tokens, idx, options)
}

md.renderer.rules.link_open = function(tokens, idx, options, _env, self) {
  const token = tokens[idx]
  if (!token) {
    return defaultLinkOpen(tokens, idx, options, _env, self)
  }
  
  // 为所有链接添加 target="_blank" 和 rel="noopener noreferrer"
  const aIndex = token.attrIndex('target')
  if (aIndex < 0) {
    token.attrPush(['target', '_blank'])
  } else {
    if (token.attrs?.[aIndex]) token.attrs[aIndex][1] = '_blank'
  }
  
  const relIndex = token.attrIndex('rel')
  if (relIndex < 0) {
    token.attrPush(['rel', 'noopener noreferrer'])
  } else {
    if (token.attrs?.[relIndex]) token.attrs[relIndex][1] = 'noopener noreferrer'
  }
  
  return defaultLinkOpen(tokens, idx, options, _env, self)
}

export function renderMarkdown(content: string): string {
  return sanitizeHtml(md.render(content || ''))
}
