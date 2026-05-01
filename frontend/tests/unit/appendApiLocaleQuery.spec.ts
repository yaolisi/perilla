import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { appendApiLocaleQuery, getApiLocaleQueryParam } from '@/services/api'

function attachMockLocalStorage(store: Record<string, string>) {
  vi.stubGlobal(
    'localStorage',
    {
      getItem: (k: string) => (k in store ? store[k] : null),
      setItem: (k: string, v: string) => {
        store[k] = v
      },
      removeItem: (k: string) => {
        delete store[k]
      },
      clear: () => {
        for (const k of Object.keys(store)) delete store[k]
      },
      key: () => null,
      get length() {
        return Object.keys(store).length
      },
    } as Storage,
  )
}

describe('appendApiLocaleQuery / getApiLocaleQueryParam', () => {
  const store: Record<string, string> = {}

  beforeEach(() => {
    for (const k of Object.keys(store)) delete store[k]
    attachMockLocalStorage(store)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('getApiLocaleQueryParam reflects platform-language', () => {
    expect(getApiLocaleQueryParam()).toBe('en')
    store['platform-language'] = 'zh'
    expect(getApiLocaleQueryParam()).toBe('zh')
  })

  it('appendApiLocaleQuery adds lang to absolute URLs', () => {
    store['platform-language'] = 'zh'
    const out = appendApiLocaleQuery('http://localhost:8000/api/agent-sessions/x/stream?interval_ms=900')
    expect(out).toContain('lang=zh')
    expect(out).toContain('interval_ms=900')
  })
})
