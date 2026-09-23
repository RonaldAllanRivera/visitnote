import { createBrowserRouter } from 'react-router'

import { AppLayout } from '@/components/AppLayout'
import { Landing } from '@/routes/Landing'
import { NewVisit } from '@/routes/NewVisit'
import { Onboarding } from '@/routes/Onboarding'
import { Processing } from '@/routes/Processing'
import { RequireAuth } from '@/routes/RequireAuth'
import { RequireOnboarding } from '@/routes/RequireOnboarding'
import { Settings } from '@/routes/Settings'
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
          // Outside the onboarding gate, and deliberately: gating the screen that
          // clears the gate would redirect it to itself.
          { path: 'onboarding', element: <Onboarding /> },
          {
            element: <RequireOnboarding />,
            children: [
              { path: 'new', element: <NewVisit /> },
              { path: 'visits/:visitId/processing', element: <Processing /> },
              // Gated too: onboarding asks the question once, and this is where it
              // gets answered again. Someone who has never answered belongs there,
              // not here.
              { path: 'settings', element: <Settings /> },
            ],
          },
          // Ungated: an operational health screen is not capture, and a user who
          // cannot load their profile should still be able to see whether the API
          // is the reason.
          { path: 'status', element: <SystemStatus /> },
        ],
      },
    ],
  },
])
