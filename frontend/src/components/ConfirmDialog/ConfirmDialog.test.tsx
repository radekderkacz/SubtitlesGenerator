import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import ConfirmDialog from './ConfirmDialog'

describe('ConfirmDialog', () => {
  it('renders title, description and confirm/cancel buttons when open', () => {
    render(
      <ConfirmDialog
        open
        onOpenChange={() => {}}
        title="Cancel job?"
        description="The job cannot be resumed."
        confirmLabel="Cancel Job"
        onConfirm={() => {}}
        destructive
      />,
    )
    expect(screen.getByText('Cancel job?')).toBeInTheDocument()
    expect(screen.getByText('The job cannot be resumed.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancel Job' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Keep' })).toBeInTheDocument()
  })

  it('does not render when open=false', () => {
    render(
      <ConfirmDialog
        open={false}
        onOpenChange={() => {}}
        title="Cancel job?"
        description="x"
        confirmLabel="Cancel Job"
        onConfirm={() => {}}
      />,
    )
    expect(screen.queryByText('Cancel job?')).not.toBeInTheDocument()
  })

  it('fires onConfirm and closes the dialog when the confirm button is clicked', async () => {
    const onConfirm = vi.fn()
    const onOpenChange = vi.fn()
    render(
      <ConfirmDialog
        open
        onOpenChange={onOpenChange}
        title="Cancel job?"
        description="x"
        confirmLabel="Cancel Job"
        onConfirm={onConfirm}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Cancel Job' }))
    expect(onConfirm).toHaveBeenCalledTimes(1)
    // onOpenChange(false) is awaited after the async handler resolves
    await vi.waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })

  it('does not fire onConfirm when the cancel button is clicked', () => {
    const onConfirm = vi.fn()
    const onOpenChange = vi.fn()
    render(
      <ConfirmDialog
        open
        onOpenChange={onOpenChange}
        title="Cancel job?"
        description="x"
        confirmLabel="Cancel Job"
        onConfirm={onConfirm}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Keep' }))
    expect(onConfirm).not.toHaveBeenCalled()
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('uses the destructive button variant when destructive=true', () => {
    render(
      <ConfirmDialog
        open
        onOpenChange={() => {}}
        title="x"
        description="x"
        confirmLabel="Cancel Job"
        onConfirm={() => {}}
        destructive
      />,
    )
    const confirmBtn = screen.getByRole('button', { name: 'Cancel Job' })
    // shadcn destructive variant maps to bg-destructive class
    expect(confirmBtn.className).toContain('destructive')
  })
})
