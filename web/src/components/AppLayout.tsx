import { NavLink, Outlet } from 'react-router'

import { useProfile } from '@/lib/profile'
import { regimeFor } from '@/lib/regimes'

const linkClass = ({ isActive }: { isActive: boolean }) =>
  isActive ? 'text-ink underline underline-offset-4' : 'text-muted hover:text-ink'

export function AppLayout() {
  // The disclaimer is jurisdictional, not decorative: it states which document is
  // the legal record, and that differs between the two regimes. `regimeFor` falls
  // back to the permissive US wording when there is no profile, which is the case
  // on the public landing page.
  const { data: profile } = useProfile()
  const regime = regimeFor(profile?.jurisdiction)

  return (
    <div className="mx-auto flex min-h-full max-w-3xl flex-col gap-8 px-4 py-10">
      <header className="flex items-baseline justify-between gap-4 border-b border-line pb-4">
        <NavLink to="/" className="font-semibold tracking-tight">
          VisitNote<span className="text-accent"> AI</span>
        </NavLink>
        <nav className="flex gap-4 text-sm">
          <NavLink to="/" end className={linkClass}>Overview</NavLink>
          <NavLink to="/new" className={linkClass}>New note</NavLink>
          <NavLink to="/settings" className={linkClass}>Settings</NavLink>
          <NavLink to="/status" className={linkClass}>Status</NavLink>
          <NavLink to="/sign-in" className={linkClass}>Sign in</NavLink>
        </nav>
      </header>

      <main className="flex-1">
        <Outlet />
      </main>

      <footer className="border-t border-line pt-4 text-xs text-muted">{regime.disclaimer}</footer>
    </div>
  )
}
