import { describe, it, expect, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { useJobStore } from '@/store/jobStore'
import { makeJob } from '@/test-utils/mockJob'
import BackgroundProcessingToast from './BackgroundProcessingToast'

beforeEach(() => {
  useJobStore.setState({ jobs: [], isConnected: true, lastEventAt: null })
})

describe('BackgroundProcessingToast', () => {
  it('renders nothing when there are no active jobs', () => {
    const { container } = render(<BackgroundProcessingToast />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the toast when a job is queued or processing', () => {
    useJobStore.setState({
      jobs: [makeJob({ id: 'a', status: 'processing' })],
      isConnected: true,
    })
    render(<BackgroundProcessingToast />)
    expect(screen.getByText('Background Processing')).toBeInTheDocument()
    expect(screen.getByText(/1 active task in pipeline/)).toBeInTheDocument()
  })

  it('pluralizes the active-task count', () => {
    useJobStore.setState({
      jobs: [
        makeJob({ id: 'a', status: 'processing' }),
        makeJob({ id: 'b', status: 'queued' }),
      ],
      isConnected: true,
    })
    render(<BackgroundProcessingToast />)
    expect(screen.getByText(/2 active tasks in pipeline/)).toBeInTheDocument()
  })

  it('only counts active statuses (queued + processing), not terminal ones', () => {
    useJobStore.setState({
      jobs: [
        makeJob({ id: 'a', status: 'processing' }),
        makeJob({ id: 'b', status: 'completed' }),
        makeJob({ id: 'c', status: 'failed' }),
        makeJob({ id: 'd', status: 'cancelled' }),
      ],
      isConnected: true,
    })
    render(<BackgroundProcessingToast />)
    expect(screen.getByText(/1 active task in pipeline/)).toBeInTheDocument()
  })

  it('clicking the dismiss button hides the toast', () => {
    useJobStore.setState({
      jobs: [makeJob({ id: 'a', status: 'processing' })],
      isConnected: true,
    })
    render(<BackgroundProcessingToast />)
    fireEvent.click(screen.getByRole('button', { name: /Dismiss/ }))
    expect(screen.queryByText('Background Processing')).not.toBeInTheDocument()
  })
})
