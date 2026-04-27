import { describe, expect, it } from 'vitest'
import {
  ensureSupportedStatusDeltaSchemaVersion,
  mergeAgentSessionDelta,
  mergeWorkflowExecutionDelta,
  STATUS_DELTA_SCHEMA_MISMATCH_ERROR_CODE,
  StatusDeltaSchemaVersionError,
  type AgentSessionStatusDelta,
  type WorkflowExecutionStatusDelta,
} from '@/utils/streamDeltas'

describe('streamDeltas', () => {
  it('merges agent session delta without dropping other fields', () => {
    const current = {
      session_id: 's1',
      agent_id: 'a1',
      user_id: 'u1',
      trace_id: 't1',
      messages: [{ role: 'user' as const, content: 'hello' }],
      step: 1,
      status: 'running' as const,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      error_message: null as string | null,
    }
    const delta: AgentSessionStatusDelta = {
      schema_version: 1,
      session_id: 's1',
      status: 'error',
      step: 2,
      updated_at: '2026-01-01T00:00:02Z',
      error_message: 'boom',
      messages_count: 1,
    }
    const next = mergeAgentSessionDelta(current, delta)
    expect(next.session_id).toBe('s1')
    expect(next.status).toBe('error')
    expect(next.step).toBe(2)
    expect(next.updated_at).toBe('2026-01-01T00:00:02Z')
    expect(next.error_message).toBe('boom')
    expect(next.messages).toHaveLength(1)
  })

  it('merges workflow execution delta without dropping payload', () => {
    const current = {
      execution_id: 'e1',
      workflow_id: 'w1',
      version_id: 'v1',
      state: 'running',
      input_data: { q: 'x' },
      created_at: '2026-01-01T00:00:00Z',
      started_at: '2026-01-01T00:00:01Z',
      finished_at: null as string | null,
      duration_ms: 10,
      queue_position: 1,
      wait_duration_ms: 3,
    }
    const delta: WorkflowExecutionStatusDelta = {
      schema_version: 1,
      execution_id: 'e1',
      workflow_id: 'w1',
      version_id: 'v1',
      state: 'completed',
      started_at: '2026-01-01T00:00:01Z',
      finished_at: '2026-01-01T00:00:05Z',
      duration_ms: 4000,
      queue_position: 0,
      wait_duration_ms: 3,
      node_timeline_count: 5,
    }
    const next = mergeWorkflowExecutionDelta(current, delta)
    expect(next.execution_id).toBe('e1')
    expect(next.state).toBe('completed')
    expect(next.finished_at).toBe('2026-01-01T00:00:05Z')
    expect(next.duration_ms).toBe(4000)
    expect(next.input_data).toEqual({ q: 'x' })
  })

  it('accepts supported status_delta schema version', () => {
    expect(() => ensureSupportedStatusDeltaSchemaVersion({ schema_version: 1 }, 'agent')).not.toThrow()
    expect(() => ensureSupportedStatusDeltaSchemaVersion({}, 'workflow')).not.toThrow()
  })

  it('rejects future status_delta schema version', () => {
    try {
      ensureSupportedStatusDeltaSchemaVersion({ schema_version: 2 }, 'workflow')
      throw new Error('expected schema mismatch error')
    } catch (error) {
      expect(error).toBeInstanceOf(StatusDeltaSchemaVersionError)
      const mismatch = error as StatusDeltaSchemaVersionError
      expect(mismatch.error_code).toBe(STATUS_DELTA_SCHEMA_MISMATCH_ERROR_CODE)
      expect(mismatch.stream_name).toBe('workflow')
      expect(mismatch.reason).toBe('unsupported')
    }
  })
})

