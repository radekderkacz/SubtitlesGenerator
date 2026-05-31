import { lazy, Suspense } from 'react'
import { createBrowserRouter, RouterProvider, Navigate } from 'react-router'
import Layout from '@/components/Layout/Layout'
import QueuePage from '@/pages/Queue/QueuePage'

// Code-split the secondary routes — only the Queue (the index) ships in the
// main bundle. Library / Job Detail / Settings / History / Automations each
// load on demand the first time the user navigates to them.
const FileBrowserPage = lazy(() => import('@/pages/FileBrowser/FileBrowserPage'))
const JobDetailPage = lazy(() => import('@/pages/JobDetail/JobDetailPage'))
const SettingsPage = lazy(() => import('@/pages/Settings/SettingsPage'))
const HistoryPage = lazy(() => import('@/pages/History/HistoryPage'))
const AutomationsPage = lazy(() => import('@/pages/Automations/AutomationsPage'))

function PageFallback() {
  return (
    <output className="block max-w-[1280px] mx-auto p-6 text-sm text-muted-foreground">
      Loading…
    </output>
  )
}

function withSuspense(node: React.ReactNode): React.ReactNode {
  return <Suspense fallback={<PageFallback />}>{node}</Suspense>
}

export const routes = [
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <QueuePage /> },
      { path: 'browse', element: withSuspense(<FileBrowserPage />) },
      { path: 'jobs/:id', element: withSuspense(<JobDetailPage />) },
      { path: 'settings', element: <Navigate to="/settings/media" replace /> },
      { path: 'settings/:section', element: withSuspense(<SettingsPage />) },
      { path: 'history', element: withSuspense(<HistoryPage />) },
      { path: 'automations', element: withSuspense(<AutomationsPage />) },
    ],
  },
]

export const router = createBrowserRouter(routes)

export default function App() {
  return <RouterProvider router={router} />
}
