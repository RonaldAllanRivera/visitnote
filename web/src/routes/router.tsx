import { createBrowserRouter } from 'react-router'

import { AppLayout } from '@/components/AppLayout'
import { Landing } from '@/routes/Landing'
import { SystemStatus } from '@/routes/SystemStatus'

/**
 * Zones are split at the route level. The marketing page must stay small -- it is the
 * first thing a visitor downloads -- so the authenticated zones are lazily loaded as
 * they are built out in later phases.
 */
export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Landing /> },
      { path: 'status', element: <SystemStatus /> },
    ],
  },
])
