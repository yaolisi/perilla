import { describe, expect, it } from 'vitest'
import type { Edge, Node } from '@vue-flow/core'
import {
  validateWorkflowNodes,
  validateWorkflowPreflight,
} from '@/components/workflow/editor/validation'
import type { WorkflowNodeData } from '@/components/workflow/editor/types'

describe('workflow validation i18n keys', () => {
  it('returns messageKey for all validateWorkflowNodes errors', () => {
    const nodes = [
      {
        id: 'in-1',
        type: 'workflow',
        position: { x: 0, y: 0 },
        data: {
          type: 'input',
          label: 'Input',
          config: {
            input_key: 1,
            fixed_input: [],
            input_schema: [],
          },
        },
      },
      {
        id: 'out-1',
        type: 'workflow',
        position: { x: 100, y: 0 },
        data: {
          type: 'output',
          label: 'Output',
          config: {
            expression: '${input.query}',
            output_key: '',
          },
        },
      },
      {
        id: 'sub-1',
        type: 'workflow',
        position: { x: 200, y: 0 },
        data: {
          type: 'sub_workflow',
          label: 'Sub',
          config: {
            target_workflow_id: '',
            target_version_selector: 'invalid',
            input_mapping: [],
            output_mapping: [],
          },
        },
      },
    ] as Node<WorkflowNodeData>[]

    const result = validateWorkflowNodes(nodes)
    expect(result.valid).toBe(false)
    expect(result.errors.length).toBeGreaterThan(0)
    expect(result.errors.every((e) => Boolean(e.messageKey))).toBe(true)
    expect(result.errors.some((e) => e.messageKey === 'workflow_editor.input_key_string_only')).toBe(true)
    expect(result.errors.some((e) => e.messageKey === 'workflow_editor.subworkflow_selector_unsupported')).toBe(true)
  })

  it('returns messageKey for all validateWorkflowPreflight errors', () => {
    const nodes = [
      {
        id: 'input-1',
        type: 'workflow',
        position: { x: 0, y: 0 },
        data: {
          type: 'input',
          label: 'Input',
          config: {
            fixed_input: { query: '' },
          },
        },
      },
      {
        id: 'cond-1',
        type: 'workflow',
        position: { x: 100, y: 0 },
        data: {
          type: 'condition',
          label: 'Condition',
          config: {
            condition_expression: '${input.unknown} == "x" || ${nodes.missing.output} || ${input.query}',
          },
        },
      },
    ] as Node<WorkflowNodeData>[]
    const edges: Edge[] = []

    const result = validateWorkflowPreflight(nodes, edges)
    expect(result.valid).toBe(false)
    expect(result.errors.length).toBeGreaterThan(0)
    expect(result.errors.every((e) => Boolean(e.messageKey))).toBe(true)
    expect(result.errors.some((e) => e.messageKey === 'workflow_editor.condition_variable_missing')).toBe(true)
    expect(result.errors.some((e) => e.messageKey === 'workflow_editor.condition_node_reference_missing')).toBe(true)
    expect(result.errors.some((e) => e.messageKey === 'workflow_editor.condition_branch_incomplete')).toBe(true)
  })
})
