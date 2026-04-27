export interface AgentSessionStatusDelta {
  schema_version: number
  session_id: string
  status: 'running' | 'finished' | 'error' | 'idle'
  step: number
  updated_at: string
  error_message?: string | null
  messages_count: number
}

export interface WorkflowExecutionStatusDelta {
  schema_version: number
  execution_id: string
  workflow_id: string
  version_id: string
  state: string
  started_at?: string | null
  finished_at?: string | null
  duration_ms?: number | null
  queue_position?: number | null
  wait_duration_ms?: number | null
  node_timeline_count: number
}

const SUPPORTED_STATUS_DELTA_SCHEMA_VERSION = 1
export const STATUS_DELTA_SCHEMA_MISMATCH_ERROR_CODE = 'sse_delta_schema_mismatch'

export class StatusDeltaSchemaVersionError extends Error {
  error_code: string
  stream_name: string
  schema_version: number | null
  supported_schema_version: number
  reason: 'invalid' | 'unsupported'

  constructor(params: {
    streamName: string
    schemaVersion: number | null
    supportedSchemaVersion: number
    reason: 'invalid' | 'unsupported'
  }) {
    const { streamName, schemaVersion, supportedSchemaVersion, reason } = params
    const detail =
      reason === 'unsupported'
        ? `${schemaVersion} > ${supportedSchemaVersion}`
        : String(schemaVersion)
    super(`${streamName} status_delta schema_version ${reason}: ${detail}`)
    this.name = 'StatusDeltaSchemaVersionError'
    this.error_code = STATUS_DELTA_SCHEMA_MISMATCH_ERROR_CODE
    this.stream_name = streamName
    this.schema_version = schemaVersion
    this.supported_schema_version = supportedSchemaVersion
    this.reason = reason
  }
}

export function ensureSupportedStatusDeltaSchemaVersion(
  payload: { schema_version?: unknown },
  streamName: string
): void {
  const raw = payload?.schema_version
  const schemaVersion = typeof raw === 'number' ? raw : Number(raw ?? SUPPORTED_STATUS_DELTA_SCHEMA_VERSION)
  if (!Number.isFinite(schemaVersion) || schemaVersion < 1) {
    throw new StatusDeltaSchemaVersionError({
      streamName,
      schemaVersion: Number.isFinite(schemaVersion) ? schemaVersion : null,
      supportedSchemaVersion: SUPPORTED_STATUS_DELTA_SCHEMA_VERSION,
      reason: 'invalid',
    })
  }
  if (schemaVersion > SUPPORTED_STATUS_DELTA_SCHEMA_VERSION) {
    throw new StatusDeltaSchemaVersionError({
      streamName,
      schemaVersion,
      supportedSchemaVersion: SUPPORTED_STATUS_DELTA_SCHEMA_VERSION,
      reason: 'unsupported',
    })
  }
}

export function mergeAgentSessionDelta<T extends {
    status: 'running' | 'finished' | 'error' | 'idle'
    step: number
    updated_at: string
    error_message?: string | null
  }>(
  current: T,
  delta: AgentSessionStatusDelta
): T {
  return {
    ...current,
    status: delta.status,
    step: delta.step,
    updated_at: delta.updated_at,
    error_message: delta.error_message ?? null,
  }
}

export function mergeWorkflowExecutionDelta<T extends {
    state: string
    started_at?: string | null
    finished_at?: string | null
    duration_ms?: number | null
    queue_position?: number | null
    wait_duration_ms?: number | null
  }>(
  current: T,
  delta: WorkflowExecutionStatusDelta
): T {
  return {
    ...current,
    state: delta.state,
    started_at: delta.started_at ?? current.started_at,
    finished_at: delta.finished_at ?? current.finished_at,
    duration_ms: delta.duration_ms ?? current.duration_ms,
    queue_position: delta.queue_position ?? current.queue_position,
    wait_duration_ms: delta.wait_duration_ms ?? current.wait_duration_ms,
  }
}

