import { afterEach } from 'vitest'

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = ResizeObserverMock as any

afterEach(() => {
  document.body.innerHTML = ''
})
