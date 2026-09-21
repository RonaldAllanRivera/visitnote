import { beforeEach, describe, expect, it, vi } from 'vitest'

import { uploadAudio } from './uploadAudio'

const MEGABYTE = 1024 * 1024

function blob(size: number): Blob {
  return new Blob([new Uint8Array(size)], { type: 'audio/webm' })
}

/** A ticket as the API returns it for a multipart upload. */
function multipartTicket(partCount: number) {
  return {
    mode: 'multipart' as const,
    upload_id: 'upload-1',
    part_size_bytes: 8 * MEGABYTE,
    parts: Array.from({ length: partCount }, (_, index) => ({
      part_number: index + 1,
      url: `https://storage.test/part-${String(index + 1)}`,
    })),
  }
}

describe('uploadAudio', () => {
  let putPart: ReturnType<typeof vi.fn>
  let reissue: ReturnType<typeof vi.fn>

  beforeEach(() => {
    // Resolves with the ETag storage would return for the uploaded part.
    putPart = vi.fn().mockImplementation((_url: string, _body: Blob, index: number) =>
      Promise.resolve(`etag-${String(index)}`),
    )
    reissue = vi.fn()
  })

  it('uses the single presigned PUT for a small recording', async () => {
    const ticket = { mode: 'single' as const, url: 'https://storage.test/put', parts: [] }

    const result = await uploadAudio({ blob: blob(1024), ticket, putPart, reissue })

    expect(putPart).toHaveBeenCalledOnce()
    expect(result.parts).toEqual([])
  })

  it('uploads one request per part for a large recording', async () => {
    const ticket = multipartTicket(3)

    await uploadAudio({ blob: blob(20 * MEGABYTE), ticket, putPart, reissue })

    expect(putPart).toHaveBeenCalledTimes(3)
  })

  it('returns the part list in ascending order with its etags', async () => {
    // S3 rejects a completion whose parts are out of order, and the error it gives
    // back does not say so.
    const ticket = multipartTicket(3)

    const result = await uploadAudio({ blob: blob(20 * MEGABYTE), ticket, putPart, reissue })

    expect(result.parts).toEqual([
      { part_number: 1, etag: 'etag-1' },
      { part_number: 2, etag: 'etag-2' },
      { part_number: 3, etag: 'etag-3' },
    ])
  })

  it('reports progress as parts complete', async () => {
    const onProgress = vi.fn()

    await uploadAudio({
      blob: blob(20 * MEGABYTE),
      ticket: multipartTicket(4),
      putPart,
      reissue,
      onProgress,
    })

    // Monotonic, and finishes at 1. A progress bar that jumps backwards reads as a
    // failure to the person holding the phone.
    const values = onProgress.mock.calls.map(([value]) => value as number)
    expect(values).toEqual([...values].sort((a, b) => a - b))
    expect(values.at(-1)).toBe(1)
  })

  it('retries only the part that failed', async () => {
    // Re-uploading everything because part 2 of 12 timed out is how a field upload
    // over cellular never finishes.
    putPart
      .mockRejectedValueOnce(new Error('network'))
      .mockImplementation((_url: string, _body: Blob, index: number) =>
        Promise.resolve(`etag-${String(index)}`),
      )

    const result = await uploadAudio({
      blob: blob(20 * MEGABYTE),
      ticket: multipartTicket(3),
      putPart,
      reissue,
    })

    expect(putPart).toHaveBeenCalledTimes(4)
    expect(result.parts).toHaveLength(3)
  })

  it('requests fresh urls when a part url has expired', async () => {
    // Presigned URLs are short-lived and a field upload can outlive one. Resuming
    // must continue the same upload; starting over orphans every transferred part.
    putPart
      .mockRejectedValueOnce(Object.assign(new Error('expired'), { status: 403 }))
      .mockImplementation((_url: string, _body: Blob, index: number) =>
        Promise.resolve(`etag-${String(index)}`),
      )
    reissue.mockResolvedValue([{ part_number: 1, url: 'https://storage.test/fresh-1' }])

    await uploadAudio({
      blob: blob(20 * MEGABYTE),
      ticket: multipartTicket(2),
      putPart,
      reissue,
    })

    expect(reissue).toHaveBeenCalledWith([1])
  })

  it('gives up after exhausting retries for a part', async () => {
    putPart.mockRejectedValue(new Error('network'))

    await expect(
      uploadAudio({ blob: blob(20 * MEGABYTE), ticket: multipartTicket(2), putPart, reissue }),
    ).rejects.toThrow()
  })

  it('stops immediately when the caller aborts', async () => {
    const controller = new AbortController()
    controller.abort()

    await expect(
      uploadAudio({
        blob: blob(20 * MEGABYTE),
        ticket: multipartTicket(3),
        putPart,
        reissue,
        signal: controller.signal,
      }),
    ).rejects.toThrow(/abort/i)
    expect(putPart).not.toHaveBeenCalled()
  })
})
