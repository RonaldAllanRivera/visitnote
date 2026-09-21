import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RefreshCoordinator } from './refreshCoordinator'

describe('RefreshCoordinator', () => {
  let refresh: ReturnType<typeof vi.fn>

  beforeEach(() => {
    refresh = vi.fn()
  })

  it('returns the refreshed access token', async () => {
    refresh.mockResolvedValue('new-access-token')
    const coordinator = new RefreshCoordinator(refresh)

    await expect(coordinator.refresh()).resolves.toBe('new-access-token')
  })

  it('performs a single refresh when several requests fail at once', async () => {
    // The bug this prevents: a dashboard mounts six queries, the access token has
    // expired, and six concurrent 401s fire six refreshes. With rotation, five of
    // those present an already-rotated token -- which the server correctly reads as
    // token theft and kills the session. Deduplication is what stops the client
    // attacking itself.
    refresh.mockImplementation(
      () => new Promise((resolve) => setTimeout(() => { resolve('new-access-token') }, 10)),
    )
    const coordinator = new RefreshCoordinator(refresh)

    const results = await Promise.all([
      coordinator.refresh(),
      coordinator.refresh(),
      coordinator.refresh(),
    ])

    expect(refresh).toHaveBeenCalledTimes(1)
    expect(results).toEqual(['new-access-token', 'new-access-token', 'new-access-token'])
  })

  it('rejects every waiting caller when the refresh fails', async () => {
    refresh.mockRejectedValue(new Error('session expired'))
    const coordinator = new RefreshCoordinator(refresh)

    const settled = await Promise.allSettled([coordinator.refresh(), coordinator.refresh()])

    expect(settled.map((result) => result.status)).toEqual(['rejected', 'rejected'])
    expect(refresh).toHaveBeenCalledTimes(1)
  })

  it('allows a fresh attempt after a failure', async () => {
    // A failed refresh must not poison the coordinator. The user may sign in again
    // in the same page session.
    refresh.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce('recovered')
    const coordinator = new RefreshCoordinator(refresh)

    await expect(coordinator.refresh()).rejects.toThrow('offline')
    await expect(coordinator.refresh()).resolves.toBe('recovered')
    expect(refresh).toHaveBeenCalledTimes(2)
  })

  it('starts a new refresh once the previous one has settled', async () => {
    refresh.mockResolvedValueOnce('first').mockResolvedValueOnce('second')
    const coordinator = new RefreshCoordinator(refresh)

    await expect(coordinator.refresh()).resolves.toBe('first')
    await expect(coordinator.refresh()).resolves.toBe('second')
  })
})
