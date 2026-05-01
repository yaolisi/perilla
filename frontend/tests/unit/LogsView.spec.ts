import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import zhLocale from '@/i18n/locales/zh.json'
import LogsView from '@/components/logs/LogsView.vue'

const { streamLogsMock } = vi.hoisted(() => ({
  streamLogsMock: vi.fn(),
}))

vi.mock('@/services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/api')>()
  return {
    ...actual,
    streamLogs: streamLogsMock,
  }
})

function makeI18n() {
  return createI18n({
    legacy: false,
    locale: 'zh',
    messages: { zh: { logs: zhLocale.logs } },
    missingWarn: false,
    fallbackWarn: false,
  })
}

describe('LogsView', () => {
  beforeEach(() => {
    streamLogsMock.mockImplementation((onLog: (entry: unknown) => void) => {
      queueMicrotask(() =>
        onLog({
          timestamp: '2026-01-01T00:00:00Z',
          level: 'INFO',
          tag: 'test',
          message: 'hello-stream',
        }),
      )
      return () => {}
    })
  })

  afterEach(() => {
    streamLogsMock.mockReset()
  })

  it('renders title and displays streamed log entry', async () => {
    const wrapper = mount(LogsView, {
      global: { plugins: [makeI18n()] },
    })
    expect(wrapper.text()).toContain(zhLocale.logs.title)
    await flushPromises()
    expect(wrapper.text()).toContain('hello-stream')
    expect(wrapper.text()).toContain('INFO')
    expect(streamLogsMock).toHaveBeenCalled()
  })
})
