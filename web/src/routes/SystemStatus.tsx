import { useQuery } from '@tanstack/react-query'

import { api } from '@/api/client'
import { queryKeys } from '@/lib/queryClient'

/**
 * Proves the whole client-to-API path end to end: generated types, the typed fetch
 * client, TanStack Query, and the running backend. If this page renders real latency
 * numbers, the contract pipeline works.
 */
export function SystemStatus() {
  const { data, isPending, isError } = useQuery({
    queryKey: queryKeys.health(),
    queryFn: async () => {
      const { data, error, response } = await api.GET('/healthz')
      // A 503 body is a valid HealthResponse describing which dependency failed, so
      // it is surfaced as an error rather than rendered as if the system were well.
      if (error ?? !response.ok) {
        throw new Error(`health check failed with status ${String(response.status)}`)
      }
      return data
    },
    refetchInterval: 10_000,
  })

  if (isPending) return <p className="text-muted">Checking…</p>
  if (isError) return <p className="text-critical">API unreachable.</p>

  return (
    <section className="space-y-4">
      <div className="flex items-baseline gap-3">
        <h2 className="text-lg font-medium">System status</h2>
        <span className="text-sm text-muted">
          {data.environment} · v{data.version}
        </span>
      </div>

      <table className="w-full max-w-md border-collapse text-sm">
        <caption className="sr-only">Dependency health</caption>
        <thead>
          <tr className="border-b border-line text-left text-muted">
            <th scope="col" className="py-2 font-medium">Dependency</th>
            <th scope="col" className="py-2 font-medium">Status</th>
            <th scope="col" className="py-2 text-right font-medium">Latency</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(data.dependencies ?? {}).map(([name, dep]) => (
            <tr key={name} className="border-b border-line">
              <th scope="row" className="py-2 text-left font-normal">{name}</th>
              <td className={dep.status === 'ok' ? 'py-2' : 'py-2 text-critical'}>
                {dep.status}
              </td>
              <td className="py-2 text-right tabular-nums text-muted">
                {dep.latency_ms != null ? `${String(dep.latency_ms)} ms` : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
