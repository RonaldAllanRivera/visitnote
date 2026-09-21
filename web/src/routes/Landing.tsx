export function Landing() {
  return (
    <section className="space-y-6">
      <div className="space-y-3">
        <h1 className="text-3xl font-semibold tracking-tight text-balance">
          Turn your visit into a finished, compliant note in two minutes.
        </h1>
        <p className="max-w-prose text-muted">
          Record the visit or dictate a recap. VisitNote structures it into the right
          note format and flags every element a reviewer would expect to find and did
          not — before you sign it.
        </p>
      </div>

      <p className="max-w-prose rounded-md border border-line p-4 text-sm text-muted">
        <strong className="font-medium text-ink">Demo mode.</strong>{' '}
        This deployment processes fictional audio only. Real patient recordings require
        executed Business Associate Agreements with every provider in the pipeline.
      </p>
    </section>
  )
}
