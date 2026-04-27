import { describe, expect, it } from 'vitest'
import { NODE_LIBRARY } from '@/components/workflow/editor/types'

describe('workflow node library i18n contract', () => {
  it('ensures every node library item has labelKey', () => {
    const missing = NODE_LIBRARY.filter((item) => !item.labelKey).map((item) => item.type)
    expect(missing).toEqual([])
  })

  it('ensures disabled items provide disabledReasonKey', () => {
    const missing = NODE_LIBRARY
      .filter((item) => item.disabled)
      .filter((item) => !item.disabledReasonKey)
      .map((item) => item.type)
    expect(missing).toEqual([])
  })
})
