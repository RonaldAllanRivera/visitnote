import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { detailMessage } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryClient'

export type Note = components['schemas']['NoteRead']
export type NoteListItem = components['schemas']['NoteListItem']
export type SectionSpec = components['schemas']['SectionSpecRead']
export type NoteFlag = components['schemas']['NoteFlagRead']
export type SectionValue = Note['sections'][string]

/** Thrown when the note moved on while it was open. Carries where it moved to. */
export class NoteConflictError extends Error {
  constructor(readonly currentVersion: number) {
    super('This note was changed somewhere else.')
    this.name = 'NoteConflictError'
  }
}

export function useNote(noteId: string) {
  return useQuery({
    queryKey: queryKeys.note(noteId),
    queryFn: async (): Promise<Note> => {
      const { data, response } = await api.GET('/api/v1/notes/{note_id}', {
        params: { path: { note_id: noteId } },
      })
      if (!response.ok || !data) throw new Error('Could not load this note')
      return data
    },
    // The editor holds a draft derived from this. Refetching underneath an open form
    // would replace what the nurse is typing with what the server last sent.
    staleTime: Infinity,
  })
}

export function useNotes() {
  return useQuery({
    queryKey: queryKeys.notes(),
    queryFn: async (): Promise<NoteListItem[]> => {
      const { data, response } = await api.GET('/api/v1/notes')
      if (!response.ok || !data) throw new Error('Could not load your notes')
      return data
    },
  })
}

export function useSaveNote(noteId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: components['schemas']['NoteUpdate']): Promise<Note> => {
      const { data, error, response } = await api.PATCH('/api/v1/notes/{note_id}', {
        params: { path: { note_id: noteId } },
        body,
      })
      if (response.status === 409) {
        const detail = (error as { detail?: { current_version?: number } } | undefined)?.detail
        throw new NoteConflictError(detail?.current_version ?? 0)
      }
      if (error ?? !data) throw new Error(detailMessage(error, 'Could not save this note'))
      return data
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.note(noteId), saved)
      // The list shows edited state and flag counts, so it is stale the moment a
      // save lands.
      void queryClient.invalidateQueries({ queryKey: queryKeys.notes() })
    },
  })
}
