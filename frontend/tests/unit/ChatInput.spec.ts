import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { defineComponent, h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import ChatInput from '@/components/chat/ChatInput.vue'

vi.mock('@/services/api', () => ({
  asrTranscribe: vi.fn(),
}))

vi.mock('@/components/ui/textarea', () => ({
  Textarea: defineComponent({
    props: { modelValue: { type: String, default: '' } },
    emits: ['update:modelValue', 'keydown'],
    setup(props, { emit, attrs }) {
      return () =>
        h('textarea', {
          ...attrs,
          value: props.modelValue,
          onInput: (e: Event) => emit('update:modelValue', (e.target as HTMLTextAreaElement).value),
          onKeydown: (e: KeyboardEvent) => emit('keydown', e),
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

vi.mock('@/components/ui/badge', () => ({
  Badge: defineComponent({
    setup(_, { slots, attrs }) {
      return () => h('span', attrs, slots.default?.())
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
          input_placeholder: '请输入',
          input_footer: '内容由 AI 生成',
          web_search: '联网',
          vision: '视觉',
          voice_start: '开始语音',
          voice_stop: '停止语音',
          voice_transcribing: '识别中',
        },
      },
    },
    missingWarn: false,
    fallbackWarn: false,
  })
}

function mountChatInput(props: Record<string, unknown> = {}) {
  return mount(ChatInput, {
    props,
    global: { plugins: [makeI18n()] },
  })
}

async function selectFiles(wrapper: ReturnType<typeof mountChatInput>, files: File[]) {
  const fileInput = wrapper.find('input[type="file"]')
  Object.defineProperty(fileInput.element, 'files', {
    value: files,
    configurable: true,
  })
  await fileInput.trigger('change')
}

describe('ChatInput', () => {
  it('emits send when message has no files', async () => {
    const wrapper = mountChatInput()
    const textarea = wrapper.find('textarea')
    await textarea.setValue('你好')

    const sendButton = wrapper.findAll('button').at(-1)
    expect(sendButton).toBeTruthy()
    await sendButton!.trigger('click')

    const sendEvents = wrapper.emitted('send')
    expect(sendEvents).toBeTruthy()
    expect(sendEvents?.[0]).toEqual(['你好'])
    expect(wrapper.emitted('send-with-files')).toBeFalsy()
    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('')
  })

  it('filters non-image files and emits send-with-files', async () => {
    const wrapper = mountChatInput()
    const image = new File(['img'], 'a.png', { type: 'image/png' })
    const text = new File(['txt'], 'a.txt', { type: 'text/plain' })

    await selectFiles(wrapper, [image, text])
    expect(wrapper.findAll('img').length).toBe(1)

    await wrapper.find('textarea').setValue('带图提问')
    const sendButton = wrapper.findAll('button').at(-1)
    await sendButton!.trigger('click')

    const sendWithFilesEvents = wrapper.emitted('send-with-files')
    expect(sendWithFilesEvents).toBeTruthy()
    expect(sendWithFilesEvents?.[0]?.[0]).toBe('带图提问')
    expect((sendWithFilesEvents?.[0]?.[1] as File[]).map((f) => f.name)).toEqual(['a.png'])
    expect(wrapper.findAll('img').length).toBe(0)
  })

  it('does not emit send events when disabled', async () => {
    const wrapper = mountChatInput({ disabled: true })
    await wrapper.find('textarea').setValue('不会发送')

    const sendButton = wrapper.findAll('button').at(-1)
    await sendButton!.trigger('click')

    expect(wrapper.emitted('send')).toBeFalsy()
    expect(wrapper.emitted('send-with-files')).toBeFalsy()
  })

  it('shows warning for image attachments on non-vision model and clears on downgrade', async () => {
    const wrapper = mountChatInput({ modelId: 'auto', modelSupportsVision: false })
    const image = new File(['img'], 'b.png', { type: 'image/png' })
    await selectFiles(wrapper, [image])

    expect(wrapper.text()).not.toContain('当前模型不支持图片')
    expect(wrapper.findAll('img').length).toBe(1)

    await wrapper.setProps({ modelId: 'text-only', modelSupportsVision: false })
    expect(wrapper.findAll('img').length).toBe(0)

    await selectFiles(wrapper, [image])
    expect(wrapper.text()).toContain('chat.vision.model_not_supported')
  })
})
