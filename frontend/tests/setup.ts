import { afterEach } from 'vitest'

// jsdom 未实现 scrollIntoView；组件里若直接调用会在 Vitest 中产生未处理的 rejection
if (typeof Element !== 'undefined' && typeof Element.prototype.scrollIntoView !== 'function') {
  Element.prototype.scrollIntoView = function scrollIntoViewPolyfill() {}
}

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = ResizeObserverMock as any

afterEach(() => {
  document.body.innerHTML = ''
})
