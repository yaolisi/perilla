import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getApiAcceptLanguage } from '@/services/api'

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

describe('getApiAcceptLanguage', () => {
  const store: Record<string, string> = {}

  beforeEach(() => {
    for (const k of Object.keys(store)) delete store[k]
    attachMockLocalStorage(store)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('returns English preference when unset', () => {
    expect(getApiAcceptLanguage()).toMatch(/^en/)
  })

  it('returns Chinese preference when platform-language is zh', () => {
    store['platform-language'] = 'zh'
    expect(getApiAcceptLanguage()).toMatch(/^zh-CN/)
    expect(getApiAcceptLanguage()).toContain('en;q=0.5')
  })

  it('returns English when stored locale is en', () => {
    store['platform-language'] = 'en'
    expect(getApiAcceptLanguage()).toMatch(/^en-US/)
  })
})
