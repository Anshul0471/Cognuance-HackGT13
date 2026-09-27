import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { AuthProvider } from './auth/AuthProvider'
import { queryRetryDelay, shouldRetryQuery } from './lib/api'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: false,
      // Bounded retries for transient read failures; never auth, access, validation or conflict errors.
      retry: shouldRetryQuery,
      retryDelay: queryRetryDelay,
    },
    mutations: { retry: false },
  },
})

// A data router (rather than <BrowserRouter>) so pages can guard unsent drafts with useBlocker.
const router = createBrowserRouter([{ path: '*', element: <App /> }])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
)
