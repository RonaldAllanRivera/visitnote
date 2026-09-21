/**
 * Uploads a recording to object storage using the ticket the API issued.
 *
 * Written for a phone on cellular in someone's home, which is the hardest network
 * this product has to work on. Three consequences shape the code:
 *
 *  - **Parts retry individually.** Re-sending the whole recording because part 2 of 12
 *    timed out is how a field upload never finishes.
 *  - **Expired URLs are recoverable.** Presigned URLs are short-lived and an upload
 *    can outlive one. A 403 means "ask for a fresh URL", not "start again" — starting
 *    again orphans every part already transferred.
 *  - **Progress only moves forward.** A bar that jumps backwards reads as a failure to
 *    the person holding the phone, even when the upload is fine.
 */

export interface TicketPart {
  part_number: number
  url: string
}

export interface UploadTicket {
  mode: 'single' | 'multipart'
  url?: string | null
  upload_id?: string | null
  part_size_bytes?: number | null
  parts: TicketPart[]
}

export interface CompletedPart {
  part_number: number
  etag: string
}

interface UploadOptions {
  blob: Blob
  ticket: UploadTicket
  /** Performs one PUT and resolves with the storage ETag for that part. */
  putPart: (url: string, body: Blob, partNumber: number) => Promise<string>
  /** Asks the API for fresh URLs for the given part numbers. */
  reissue: (partNumbers: number[]) => Promise<TicketPart[]>
  onProgress?: (fraction: number) => void
  signal?: AbortSignal
}

const MAX_ATTEMPTS_PER_PART = 3

/** A 403 or 401 from storage means the signature expired, not that the part is bad. */
function isExpiredSignature(error: unknown): boolean {
  const status = (error as { status?: number }).status
  return status === 403 || status === 401
}

function throwIfAborted(signal: AbortSignal | undefined): void {
  if (signal?.aborted === true) throw new Error('Upload aborted')
}

export async function uploadAudio({
  blob,
  ticket,
  putPart,
  reissue,
  onProgress,
  signal,
}: UploadOptions): Promise<{ parts: CompletedPart[] }> {
  throwIfAborted(signal)

  if (ticket.mode === 'single') {
    if (!ticket.url) throw new Error('single-mode ticket has no url')
    await putPart(ticket.url, blob, 1)
    onProgress?.(1)
    // A single PUT assembles nothing, so completion needs no part list.
    return { parts: [] }
  }

  const partSize = ticket.part_size_bytes ?? blob.size
  const completed: CompletedPart[] = []
  let urls = new Map(ticket.parts.map((part) => [part.part_number, part.url]))

  for (const [index, part] of ticket.parts.entries()) {
    throwIfAborted(signal)

    const start = index * partSize
    const chunk = blob.slice(start, Math.min(start + partSize, blob.size))

    let lastError: unknown
    for (let attempt = 0; attempt < MAX_ATTEMPTS_PER_PART; attempt++) {
      throwIfAborted(signal)
      const url = urls.get(part.part_number)
      if (url === undefined) throw new Error(`no url for part ${String(part.part_number)}`)

      try {
        completed.push({
          part_number: part.part_number,
          etag: await putPart(url, chunk, part.part_number),
        })
        lastError = undefined
        break
      } catch (error) {
        lastError = error
        if (isExpiredSignature(error)) {
          // Same upload, new signature. The parts already transferred stay valid.
          const fresh = await reissue([part.part_number])
          urls = new Map([...urls, ...fresh.map((p) => [p.part_number, p.url] as const)])
        }
      }
    }

    if (lastError !== undefined) {
      throw lastError instanceof Error
        ? lastError
        : new Error(`part ${String(part.part_number)} failed`)
    }

    onProgress?.((index + 1) / ticket.parts.length)
  }

  // S3 rejects a completion whose parts are out of order, with an error that does not
  // say so. Sorting here means no caller has to know that.
  completed.sort((a, b) => a.part_number - b.part_number)
  return { parts: completed }
}
