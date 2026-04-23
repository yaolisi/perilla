import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { defineComponent, h, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import SessionTitle from '@/components/chat/SessionTitle.vue'

vi.mock('@/components/ui/input', () => ({
  Input: defineComponent({
    props: { modelValue: { type: String, default: '' } },
    emits: ['update:modelValue', 'keydown', 'blur'],
    setup(props, { emit, attrs, expose }) {
      const el = ref<HTMLInputElement | null>(null)
      expose({
        focus: () => el.value?.focus(),
        select: () => el.value?.select(),
      })
      return () =>
        h('input', {
          ref: el,
          ...attrs,
          value: props.modelValue,
          onInput: (e: Event) => emit('update:modelValue', (e.target as HTMLInputElement).value),
          onKeydown: (e: KeyboardEvent) => emit('keydown', e),
          onBlur: (e: FocusEvent) => emit('blur', e),
        })
    },
  }),
}))

vi.mock('@/components/ui/button', () => ({
  Button: defineComponent({
    emits: ['click'],
    setup(_, { emit, slots, attrs }) {
      return () => h('button', { ...attrs, onClick: (e: MouseEvent) => emit('click', e) }, slots.default?.())
    },
  }),
}))

function makeI18n() {
  return createI18n({
    legacy: false,
    locale: 'zh',
    messages: {
      zh: {
        chat: {
          new_conversation: '新会话',
          title_placeholder: '输入标题',
        },
      },
    },
    missingWarn: false,
    fallbackWarn: false,
  })
}

function makeMountOptions(props: { title: string | null | undefined; sessionId: string | null }) {
  return {
    props,
    global: {
      plugins: [makeI18n()],
    },
  }
}

describe('SessionTitle', () => {
  it('shows fallback title when title is empty', () => {
    const wrapper = mount(SessionTitle, makeMountOptions({ title: '', sessionId: null }))

    expect(wrapper.text()).toContain('新会话')
    expect(wrapper.find('input').exists()).toBe(false)
  })

  it('does not enter edit mode when sessionId is null', async () => {
    const wrapper = mount(SessionTitle, makeMountOptions({ title: '会话A', sessionId: null }))

    await wrapper.find('h2').trigger('click')
    expect(wrapper.find('input').exists()).toBe(false)
    expect(wrapper.emitted('update:title')).toBeFalsy()
  })

  it('emits trimmed title when confirming edit', async () => {
    const wrapper = mount(SessionTitle, makeMountOptions({ title: '旧标题', sessionId: 's-1' }))

    await wrapper.find('h2').trigger('click')
    const input = wrapper.find('input')
    expect(input.exists()).toBe(true)

    await input.setValue('  新标题  ')
    await input.trigger('keydown', { key: 'Enter' })

    const events = wrapper.emitted('update:title')
    expect(events).toBeTruthy()
    expect(events?.[0]).toEqual(['s-1', '新标题'])
  })

  it('cancels edit on Escape without emitting event', async () => {
    const wrapper = mount(SessionTitle, makeMountOptions({ title: '旧标题', sessionId: 's-2' }))

    await wrapper.find('h2').trigger('click')
    const input = wrapper.find('input')
    await input.setValue('不会提交')
    await input.trigger('keydown', { key: 'Escape' })

    expect(wrapper.find('input').exists()).toBe(false)
    expect(wrapper.emitted('update:title')).toBeFalsy()
  })
})
