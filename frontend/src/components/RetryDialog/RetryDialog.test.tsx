import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import RetryDialog from './RetryDialog'

describe('RetryDialog', () => {
  it('renders title, settings-aware description, Keep + Retry', () => {
    render(
      <RetryDialog
        open
        onOpenChange={() => {}}
        filename="Film.mkv"
        onRetry={() => {}}
      />,
    )
    expect(screen.getByText('Retry Film.mkv?')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Keep' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    // The dialog should mention current Settings so the user understands
    // the new run won't use the original (potentially-failed) configuration.
    expect(screen.getByText(/current Settings/i)).toBeInTheDocument()
    // Smaller-model button was removed — retry always uses Settings now.
    expect(
      screen.queryByRole('button', { name: /smaller model/i }),
    ).not.toBeInTheDocument()
  })

  it('does not render when open=false', () => {
    render(
      <RetryDialog
        open={false}
        onOpenChange={() => {}}
        filename="Film.mkv"
        onRetry={() => {}}
      />,
    )
    expect(screen.queryByText('Retry Film.mkv?')).not.toBeInTheDocument()
  })

  it('fires onRetry and closes when the primary Retry button is clicked', async () => {
    const onRetry = vi.fn()
    const onOpenChange = vi.fn()
    render(
      <RetryDialog
        open
        onOpenChange={onOpenChange}
        filename="Film.mkv"
        onRetry={onRetry}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(onRetry).toHaveBeenCalledTimes(1)
    await vi.waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })

  it('Keep dismisses the dialog without firing the retry action', () => {
    const onRetry = vi.fn()
    const onOpenChange = vi.fn()
    render(
      <RetryDialog
        open
        onOpenChange={onOpenChange}
        filename="Film.mkv"
        onRetry={onRetry}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Keep' }))
    expect(onRetry).not.toHaveBeenCalled()
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })
})
