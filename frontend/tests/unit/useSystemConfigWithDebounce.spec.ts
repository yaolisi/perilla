import { beforeEach, describe, expect, it, vi } from 'vitest'

import { SYSTEM_CONFIG_CHANGE_DEBOUNCE_MS } from '@/constants/platformEvents'
import type { SystemConfig } from '@/services/api'

const { debouncedHookSpy, getSystemConfigSpy } = vi.hoisted(() => ({
  debouncedHookSpy: vi.fn(),
  getSystemConfigSpy: vi.fn<() => Promise<SystemConfig>>(),
}))

vi.mock('@/composables/useDebouncedOnSystemConfigChange', () => ({
  useDebouncedOnSystemConfigChange: debouncedHookSpy,
}))

vi.mock('@/services/api', async () => {
  const actual = await vi.importActual('@/services/api')
  return {
    ...actual,
    getSystemConfig: getSystemConfigSpy,
  }
})

import { useSystemConfigWithDebounce } from '@/composables/useSystemConfigWithDebounce'

describe('useSystemConfigWithDebounce', () => {
  beforeEach(() => {
    debouncedHookSpy.mockReset()
    getSystemConfigSpy.mockReset()
    getSystemConfigSpy.mockResolvedValue({ version: '1.2.3', settings: {} } as SystemConfig)
  })

  it('uses default debounce when only options are provided', () => {
    useSystemConfigWithDebounce({ logPrefix: 'SpecOnlyOptions' })

    expect(debouncedHookSpy).toHaveBeenCalledTimes(1)
    expect(debouncedHookSpy.mock.calls[0]?.[1]).toBe(SYSTEM_CONFIG_CHANGE_DEBOUNCE_MS)
  })

  it('respects custom debounce when number is provided', () => {
    useSystemConfigWithDebounce(1234, { logPrefix: 'SpecCustomDebounce' })

    expect(debouncedHookSpy).toHaveBeenCalledTimes(1)
    expect(debouncedHookSpy.mock.calls[0]?.[1]).toBe(1234)
  })

  it('skips debounce subscription when subscribeToPlatformConfig is false', () => {
    useSystemConfigWithDebounce({ subscribeToPlatformConfig: false })
    expect(debouncedHookSpy).not.toHaveBeenCalled()
  })

  it('refreshSystemConfig writes fetched config to ref', async () => {
    const { systemConfig, refreshSystemConfig } = useSystemConfigWithDebounce({
      subscribeToPlatformConfig: false,
    })

    expect(systemConfig.value).toBeNull()
    await refreshSystemConfig()

    expect(getSystemConfigSpy).toHaveBeenCalledTimes(1)
    expect(systemConfig.value?.version).toBe('1.2.3')
  })

  it('prefixes error logs when refresh fails', async () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    getSystemConfigSpy.mockRejectedValue(new Error('boom'))
    const { refreshSystemConfig } = useSystemConfigWithDebounce({
      subscribeToPlatformConfig: false,
      logPrefix: 'SpecLogPrefix',
    })

    await refreshSystemConfig()

    expect(errSpy).toHaveBeenCalled()
    expect(String(errSpy.mock.calls[0]?.[0] || '')).toContain('[SpecLogPrefix] Failed to load system config:')
    errSpy.mockRestore()
  })
})
