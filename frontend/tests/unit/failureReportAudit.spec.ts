import { createHash } from 'node:crypto'
import { zipSync } from 'fflate'
import { describe, expect, it } from 'vitest'
import {
  buildFailureAuditSummary,
  computeFailureReportSha256,
  extractFailureReportFromZipBytes,
  verifyFailureBundleZipAgainstExpected,
  verifyFailureReportSha256,
} from '@/utils/failureReportAudit'

describe('failureReportAudit utils', () => {
  it('builds audit summary text', () => {
    const text = buildFailureAuditSummary({
      schema: '1.1',
      redaction: true,
      redactedKeys: 12,
    })
    expect(text).toBe('schema=1.1;redaction=on;redacted_keys=12')
  })

  it('computes stable sha256 excluding report_sha256 field', async () => {
    const report = {
      workflow_id: 'wf1',
      execution_id: 'ex1',
      payload: { b: 2, a: 1 },
      report_sha256: 'ignored',
    }
    const canonical = JSON.stringify({
      execution_id: 'ex1',
      payload: { a: 1, b: 2 },
      workflow_id: 'wf1',
    })
    const expected = createHash('sha256').update(canonical, 'utf8').digest('hex')
    const actual = await computeFailureReportSha256(report)
    expect(actual).toBe(expected)
  })

  it('verifies sha256 correctly', async () => {
    const report = {
      workflow_id: 'wf1',
      execution_id: 'ex1',
      payload: { x: 1 },
    } as Record<string, unknown>
    const hash = await computeFailureReportSha256(report)
    const verified = await verifyFailureReportSha256({ ...report, report_sha256: hash })
    expect(verified.ok).toBe(true)
    expect(verified.expected).toBe(hash)
    expect(verified.actual).toBe(hash)
  })

  it('extracts failure report from zip and verifies offline against expected hash', async () => {
    const base = {
      workflow_id: 'wf1',
      execution_id: 'ex1',
      payload: { x: 1 },
    } as Record<string, unknown>
    const hash = await computeFailureReportSha256(base)
    const report = { ...base, report_sha256: hash }
    const encoded = new TextEncoder().encode(JSON.stringify(report, null, 2))
    const jsonBytes = new Uint8Array(encoded.length)
    for (let i = 0; i < encoded.length; i++) jsonBytes[i] = encoded[i]!
    const zipBytes = zipSync({ 'failure-report.json': jsonBytes })
    const parsed = extractFailureReportFromZipBytes(zipBytes)
    expect(parsed.workflow_id).toBe('wf1')
    const blob = new Blob([zipBytes], { type: 'application/zip' })
    const offline = await verifyFailureBundleZipAgainstExpected(blob, hash)
    expect(offline.ok).toBe(true)
    expect(offline.actual).toBe(hash.toLowerCase())
    expect(offline.sidecar_matches_json).toBe(null)
  })

  it('accepts matching failure-report.sha256 sidecar', async () => {
    const base = {
      workflow_id: 'wf1',
      execution_id: 'ex1',
      payload: { x: 2 },
    } as Record<string, unknown>
    const hash = await computeFailureReportSha256(base)
    const report = { ...base, report_sha256: hash }
    const encoded = new TextEncoder().encode(JSON.stringify(report, null, 2))
    const jsonBytes = new Uint8Array(encoded.length)
    for (let i = 0; i < encoded.length; i++) jsonBytes[i] = encoded[i]!
    const sideEncoded = new TextEncoder().encode(`${hash}\n`)
    const sideBytes = new Uint8Array(sideEncoded.length)
    for (let i = 0; i < sideEncoded.length; i++) sideBytes[i] = sideEncoded[i]!
    const zipBytes = zipSync({
      'failure-report.json': jsonBytes,
      'failure-report.sha256': sideBytes,
    })
    const blob = new Blob([zipBytes], { type: 'application/zip' })
    const r = await verifyFailureBundleZipAgainstExpected(blob, hash)
    expect(r.ok).toBe(true)
    expect(r.sidecar_matches_json).toBe(true)
    expect(r.sidecar_sha256).toBe(hash.toLowerCase())
  })

  it('rejects bundle when sidecar disagrees with JSON digest', async () => {
    const base = {
      workflow_id: 'wf1',
      execution_id: 'ex1',
      payload: { x: 3 },
    } as Record<string, unknown>
    const hash = await computeFailureReportSha256(base)
    const report = { ...base, report_sha256: hash }
    const encoded = new TextEncoder().encode(JSON.stringify(report, null, 2))
    const jsonBytes = new Uint8Array(encoded.length)
    for (let i = 0; i < encoded.length; i++) jsonBytes[i] = encoded[i]!
    const wrongHex = `${'a'.repeat(64)}\n`
    const sideEncoded = new TextEncoder().encode(wrongHex)
    const sideBytes = new Uint8Array(sideEncoded.length)
    for (let i = 0; i < sideEncoded.length; i++) sideBytes[i] = sideEncoded[i]!
    const zipBytes = zipSync({
      'failure-report.json': jsonBytes,
      'failure-report.sha256': sideBytes,
    })
    const blob = new Blob([zipBytes], { type: 'application/zip' })
    const r = await verifyFailureBundleZipAgainstExpected(blob, hash)
    expect(r.ok).toBe(false)
    expect(r.sidecar_matches_json).toBe(false)
    expect(r.actual).toBe(hash.toLowerCase())
    expect(r.sidecar_sha256).toBe('a'.repeat(64))
  })
})
