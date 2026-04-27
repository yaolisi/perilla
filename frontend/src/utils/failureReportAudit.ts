import { unzipSync } from 'fflate'

export type FailureReportAuditShape = Record<string, unknown> & {
  report_sha256?: string
}

/** fflate 仅把「真正的」Uint8Array 当文件体；jsdom 下 TextEncoder 结果可能不满足 instanceof，需拷贝成规范 TypedArray。 */
function asPlainUint8Array(buf: ArrayBuffer | Uint8Array): Uint8Array {
  if (buf instanceof ArrayBuffer) return new Uint8Array(buf)
  return new Uint8Array(buf)
}

function canonicalizeForHash(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => canonicalizeForHash(item))
  if (value && typeof value === 'object') {
    const src = value as Record<string, unknown>
    const out: Record<string, unknown> = {}
    const keys = Object.keys(src).sort((a, b) => a.localeCompare(b))
    for (const key of keys) {
      out[key] = canonicalizeForHash(src[key])
    }
    return out
  }
  return value
}

async function sha256Hex(text: string): Promise<string> {
  const subtle = globalThis.crypto?.subtle
  if (!subtle) throw new Error('WebCrypto subtle API unavailable')
  const data = new TextEncoder().encode(text)
  const digest = await subtle.digest('SHA-256', data)
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

export function buildFailureAuditSummary(input: {
  schema?: string
  redaction?: boolean
  redactedKeys?: number
}): string {
  const schema = input.schema || 'unknown'
  const redaction = input.redaction ? 'on' : 'off'
  const redactedKeys = input.redactedKeys ?? 0
  return `schema=${schema};redaction=${redaction};redacted_keys=${redactedKeys}`
}

export async function computeFailureReportSha256(report: FailureReportAuditShape): Promise<string> {
  const payload: Record<string, unknown> = { ...(report as Record<string, unknown>) }
  delete payload.report_sha256
  const canonical = JSON.stringify(canonicalizeForHash(payload))
  return sha256Hex(canonical)
}

export async function verifyFailureReportSha256(report: FailureReportAuditShape): Promise<{
  ok: boolean
  expected: string
  actual: string
}> {
  const expected = String(report.report_sha256 || '').trim().toLowerCase()
  if (!expected) {
    return { ok: false, expected: '', actual: '' }
  }
  const actual = (await computeFailureReportSha256(report)).toLowerCase()
  return { ok: actual === expected, expected, actual }
}

function unzipBundleFiles(buf: ArrayBuffer | Uint8Array): Record<string, Uint8Array> {
  return unzipSync(asPlainUint8Array(buf))
}

/** 从 workflow failure bundle zip 中解析 failure-report.json（UTF-8）。 */
export function extractFailureReportFromZipBytes(buf: ArrayBuffer | Uint8Array): Record<string, unknown> {
  const files = unzipBundleFiles(buf)
  const raw = files['failure-report.json']
  if (!raw) throw new Error('failure-report.json missing in zip')
  const text = new TextDecoder('utf-8', { fatal: true }).decode(raw)
  return JSON.parse(text) as Record<string, unknown>
}

function parseSidecarSha256File(raw: Uint8Array): string {
  const text = new TextDecoder('utf-8', { fatal: false }).decode(raw).trim()
  const line = (text.split(/\r?\n/)[0] ?? '').trim()
  if (!line) {
    throw new Error('failure-report.sha256 is empty')
  }
  const hex = line.toLowerCase().replace(/\s+/g, '')
  if (!/^[a-f0-9]{64}$/.test(hex)) {
    throw new Error('failure-report.sha256 must be a 64-character hex string')
  }
  return hex
}

export type FailureBundleZipVerifyResult = {
  ok: boolean
  expected: string
  actual: string
  /** 侧车文件中的 hex；无此文件时为 null */
  sidecar_sha256: string | null
  /** 无侧车文件时为 null；有文件且与 JSON 重算一致为 true */
  sidecar_matches_json: boolean | null
}

/** 对本地 zip：从 failure-report.json 重算 canonical SHA-256，并与预期比对；若存在 failure-report.sha256 则必须与 JSON 一致。 */
export async function verifyFailureBundleZipAgainstExpected(
  blob: Blob,
  expectedSha256: string,
): Promise<FailureBundleZipVerifyResult> {
  const exp = String(expectedSha256 || '').trim().toLowerCase()
  if (!exp) {
    return {
      ok: false,
      expected: '',
      actual: '',
      sidecar_sha256: null,
      sidecar_matches_json: null,
    }
  }
  const files = unzipBundleFiles(await blob.arrayBuffer())
  const rawJson = files['failure-report.json']
  if (!rawJson) throw new Error('failure-report.json missing in zip')
  const report = JSON.parse(
    new TextDecoder('utf-8', { fatal: true }).decode(rawJson),
  ) as Record<string, unknown>
  const actual = (await computeFailureReportSha256(report as FailureReportAuditShape)).toLowerCase()

  const rawSidecar = files['failure-report.sha256']
  let sidecarSha256: string | null = null
  let sidecarMatchesJson: boolean | null = null
  if (rawSidecar) {
    sidecarSha256 = parseSidecarSha256File(rawSidecar)
    sidecarMatchesJson = sidecarSha256 === actual
  }

  const expectedOk = actual === exp
  const sidecarOk = sidecarMatchesJson !== false
  const ok = expectedOk && sidecarOk
  return {
    ok,
    expected: exp,
    actual,
    sidecar_sha256: sidecarSha256,
    sidecar_matches_json: sidecarMatchesJson,
  }
}
