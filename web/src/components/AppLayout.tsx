import { NavLink, Outlet } from 'react-router'

const linkClass = ({ isActive }: { isActive: boolean }) =>
  isActive ? 'text-ink underline underline-offset-4' : 'text-muted hover:text-ink'

export function AppLayout() {
  return (
    <div className="mx-auto flex min-h-full max-w-3xl flex-col gap-8 px-4 py-10">
      <header className="flex items-baseline justify-between gap-4 border-b border-line pb-4">
        <NavLink to="/" className="font-semibold tracking-tight">
          VisitNote<span className="text-accent"> AI</span>
        </NavLink>
        <nav className="flex gap-4 text-sm">
          <NavLink to="/" end className={linkClass}>Overview</NavLink>
          <NavLink to="/status" className={linkClass}>Status</NavLink>
        </nav>
      </header>

      <main className="flex-1">
        <Outlet />
      </main>

      <footer className="border-t border-line pt-4 text-xs text-muted">
        Drafts must be reviewed by the responsible caregiver or clinician before use.
        Not medical advice or a medical device.
      </footer>
    </div>
  )
}
