import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Toaster } from '@/components/ui/sonner'
import { ApiRequestError } from './api'
import { withApiToast } from './apiToast'

describe('withApiToast', () => {
  beforeEach(() => {
    render(<Toaster />)
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('returns true and shows the success toast when fn resolves', async () => {
    const result = await withApiToast(async () => {}, { successMessage: 'Saved' })
    expect(result).toBe(true)
    expect(await screen.findByText('Saved')).toBeInTheDocument()
  })

  it('returns true without a toast when no successMessage is provided', async () => {
    const result = await withApiToast(async () => {})
    expect(result).toBe(true)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('returns false and shows the API detail when fn rejects with ApiRequestError', async () => {
    const result = await withApiToast(async () => {
      throw new ApiRequestError(500, 'INTERNAL_ERROR', 'Server is down')
    })
    expect(result).toBe(false)
    expect(await screen.findByText('Server is down')).toBeInTheDocument()
  })

  it('returns false and shows generic "Request failed" for non-ApiRequestError', async () => {
    const result = await withApiToast(async () => {
      throw new Error('boom')
    })
    expect(result).toBe(false)
    expect(await screen.findByText('Request failed')).toBeInTheDocument()
  })
})
