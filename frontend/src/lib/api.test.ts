import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  ApiRequestError,
  apiFetch,
  detailToMessage,
  browseDirectory,
  cancelOrRemoveJob,
  deleteHistory,
  downloadJobLogUrl,
  getJob,
  getJobLog,
  getWatchFolderActivity,
  listHistory,
  refreshJellyfin,
  regenerateJob,
  retryJob,
  stopAllJobs,
  submitJob,
} from './api'

const originalFetch = globalThis.fetch

function mockFetchWith(
  responder: (url: string, init?: RequestInit) => Promise<Response> | Response,
) {
  globalThis.fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    return Promise.resolve(responder(url, init))
  }) as unknown as typeof fetch
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  vi.restoreAllMocks()
})

afterEach(() => {
  globalThis.fetch = originalFetch
})

describe('apiFetch', () => {
  it('parses JSON on a 2xx response', async () => {
    mockFetchWith(() => jsonResponse({ id: '42' }))
    await expect(apiFetch<{ id: string }>('/api/v1/test')).resolves.toEqual({ id: '42' })
  })

  it('sets the JSON content-type by default', async () => {
    let capturedHeaders: Headers | undefined
    mockFetchWith((_url, init) => {
      capturedHeaders = new Headers(init?.headers)
      return jsonResponse({ ok: true })
    })
    await apiFetch('/api/v1/test', { method: 'POST', body: '{}' })
    expect(capturedHeaders?.get('content-type')).toBe('application/json')
  })

  it('throws ApiRequestError with the server detail+code when response is not ok', async () => {
    mockFetchWith(() => jsonResponse({ detail: 'boom', code: 'BOOM' }, 422))
    await expect(apiFetch('/api/v1/test')).rejects.toMatchObject({
      status: 422,
      code: 'BOOM',
      message: 'boom',
    })
  })

  it('falls back to statusText when the error body is not JSON', async () => {
    mockFetchWith(() => new Response('upstream timeout', { status: 503, statusText: 'Service Unavailable' }))
    try {
      await apiFetch('/api/v1/test')
      throw new Error('should have thrown')
    } catch (err) {
      expect(err).toBeInstanceOf(ApiRequestError)
      const e = err as ApiRequestError
      expect(e.status).toBe(503)
      expect(e.code).toBe('UNKNOWN_ERROR')
    }
  })

  it('never produces an "[object Object]" message from a FastAPI 422 array detail', async () => {
    // Regression: a bodyless POST to a body-requiring endpoint returns
    // 422 with detail = [{type,loc,msg}]. Error(message=array) used to
    // stringify to "[object Object]" and leak into the UI.
    mockFetchWith(() =>
      jsonResponse(
        { detail: [{ type: 'missing', loc: ['body'], msg: 'Field required' }] },
        422,
      ),
    )
    try {
      await apiFetch('/api/v1/settings/test-transcription', { method: 'POST' })
      throw new Error('should have thrown')
    } catch (err) {
      const e = err as ApiRequestError
      expect(e).toBeInstanceOf(ApiRequestError)
      expect(e.status).toBe(422)
      expect(e.message).toBe('Field required')
      expect(e.message).not.toContain('[object Object]')
    }
  })
})

describe('detailToMessage', () => {
  it('passes a non-empty string through unchanged', () => {
    expect(detailToMessage('boom', 'fb')).toBe('boom')
  })
  it('joins FastAPI 422 array msgs', () => {
    expect(
      detailToMessage(
        [
          { type: 'missing', loc: ['body'], msg: 'Field required' },
          { type: 'x', loc: ['body', 'url'], msg: 'Invalid URL' },
        ],
        'fb',
      ),
    ).toBe('Field required; Invalid URL')
  })
  it('uses .message / .msg on an object detail', () => {
    expect(detailToMessage({ message: 'nope' }, 'fb')).toBe('nope')
    expect(detailToMessage({ msg: 'bad' }, 'fb')).toBe('bad')
  })
  it('falls back for empty string, null, or unrecognised shapes', () => {
    expect(detailToMessage('', 'fallback')).toBe('fallback')
    expect(detailToMessage(null, 'fallback')).toBe('fallback')
    expect(detailToMessage(42, 'fallback')).toBe('fallback')
    expect(detailToMessage([{ no: 'msg' }], 'fallback')).toBe('fallback')
  })
})

describe('cancelOrRemoveJob', () => {
  it('issues DELETE on /api/v1/jobs/{id}', async () => {
    let captured: { url?: string; method?: string } = {}
    mockFetchWith((url, init) => {
      captured = { url, method: init?.method }
      return new Response(null, { status: 204 })
    })
    await cancelOrRemoveJob('abc 123')
    expect(captured.url).toBe('/api/v1/jobs/abc%20123')
    expect(captured.method).toBe('DELETE')
  })

  it('throws ApiRequestError on non-2xx', async () => {
    mockFetchWith(() => jsonResponse({ detail: 'gone', code: 'JOB_NOT_FOUND' }, 404))
    await expect(cancelOrRemoveJob('x')).rejects.toMatchObject({
      status: 404,
      code: 'JOB_NOT_FOUND',
    })
  })

  it('falls back to default error when the body is not JSON', async () => {
    mockFetchWith(() => new Response('plain', { status: 500, statusText: 'Internal' }))
    await expect(cancelOrRemoveJob('x')).rejects.toMatchObject({
      status: 500,
      code: 'UNKNOWN_ERROR',
    })
  })
})

describe('endpoint helpers route to the right URL + method', () => {
  it.each([
    [
      'submitJob',
      () => submitJob({ file_path: '/x.mkv', profile_name: 'p1', source_language: 'auto', translate: false }),
      '/api/v1/jobs',
      'POST',
    ],
    ['stopAllJobs', () => stopAllJobs(), '/api/v1/jobs/stop-all', 'POST'],
    ['browseDirectory', () => browseDirectory(), '/api/v1/files/browse', undefined],
    [
      'browseDirectory(path)',
      () => browseDirectory('/media'),
      '/api/v1/files/browse?path=%2Fmedia',
      undefined,
    ],
    ['getJob', () => getJob('abc'), '/api/v1/jobs/abc', undefined],
    [
      'getWatchFolderActivity',
      () => getWatchFolderActivity(),
      '/api/v1/watch-folders/activity',
      undefined,
    ],
    ['listHistory()', () => listHistory(), '/api/v1/history', undefined],
    ['listHistory(failed)', () => listHistory('failed'), '/api/v1/history?status=failed', undefined],
    ['deleteHistory', () => deleteHistory(), '/api/v1/history', 'DELETE'],
    [
      'refreshJellyfin',
      () => refreshJellyfin('xyz'),
      '/api/v1/jobs/xyz/jellyfin-refresh',
      'POST',
    ],
    [
      'retryJob',
      () => retryJob('abc'),
      '/api/v1/jobs/abc/retry',
      'POST',
    ],
    [
      'regenerateJob',
      () => regenerateJob('abc-123'),
      '/api/v1/jobs/abc-123/regenerate',
      'POST',
    ],
  ] as const)('%s → %s %s', async (_name, call, expectedUrl, expectedMethod) => {
    let captured: { url?: string; method?: string } = {}
    mockFetchWith((url, init) => {
      captured = { url, method: init?.method }
      return jsonResponse({ id: 'ok', deleted: 0 })
    })
    await call()
    expect(captured.url).toBe(expectedUrl)
    if (expectedMethod) expect(captured.method).toBe(expectedMethod)
  })
})

describe('getJobLog', () => {
  it('returns the raw text body on success', async () => {
    mockFetchWith(
      () =>
        new Response('LOG LINE 1\nLOG LINE 2\n', {
          status: 200,
          headers: { 'Content-Type': 'text/plain' },
        }),
    )
    await expect(getJobLog('abc')).resolves.toBe('LOG LINE 1\nLOG LINE 2\n')
  })

  it('throws ApiRequestError on 404 with the parsed code', async () => {
    mockFetchWith(() => jsonResponse({ detail: 'Log not found', code: 'LOG_NOT_FOUND' }, 404))
    await expect(getJobLog('abc')).rejects.toMatchObject({
      status: 404,
      code: 'LOG_NOT_FOUND',
    })
  })

  it('falls back to default error when the body is not JSON', async () => {
    mockFetchWith(() => new Response('boom', { status: 500, statusText: 'Internal' }))
    await expect(getJobLog('abc')).rejects.toMatchObject({
      status: 500,
      code: 'UNKNOWN_ERROR',
    })
  })
})

describe('downloadJobLogUrl', () => {
  it('encodes the id into the path', () => {
    expect(downloadJobLogUrl('abc 123')).toBe('/api/v1/history/abc%20123/log')
  })
})

describe('ApiRequestError', () => {
  it('preserves status, code, and message', () => {
    const e = new ApiRequestError(409, 'CONFLICT', 'in use')
    expect(e).toBeInstanceOf(Error)
    expect(e.status).toBe(409)
    expect(e.code).toBe('CONFLICT')
    expect(e.message).toBe('in use')
    expect(e.name).toBe('ApiRequestError')
  })
})
