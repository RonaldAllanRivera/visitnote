import { QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router'

import { onSessionExpired } from '@/api/client'
import { queryClient } from '@/lib/queryClient'
import { router } from '@/routes/router'

import './index.css'

// When a refresh finally fails, the session is over. Sending the user to sign in
// from here keeps that decision in one place instead of in every query's error path.
onSessionExpired(() => {
  void router.navigate('/sign-in', { replace: true })
})

const container = document.getElementById('root')
if (!container) throw new Error('#root missing from index.html')

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
