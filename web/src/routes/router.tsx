import { createBrowserRouter } from 'react-router'

import { AppLayout } from '@/components/AppLayout'
import { Landing } from '@/routes/Landing'
import { NewVisit } from '@/routes/NewVisit'
import { RequireAuth } from '@/routes/RequireAuth'
import { SignIn } from '@/routes/SignIn'
import { SystemStatus } from '@/routes/SystemStatus'

/**
 * Zones are split at the route level. The marketing page must stay small -- it is the
 * first thing a visitor downloads -- so the authenticated zones are lazily loaded as
 * they are built out in later phases.
 *
 * The guard is a convenience, not a control: it decides what to render, and the API
 * independently authorises every request. A guard that could be bypassed by editing
 * the URL would not expose any data, because the server never trusts the client's
 * view of who is signed in.
 */
export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Landing /> },
      { path: 'sign-in', element: <SignIn /> },
      {
        element: <RequireAuth />,
        children: [
          { path: 'new', element: <NewVisit /> },
          { path: 'status', element: <SystemStatus /> },
        ],
      },
    ],
  },
])
