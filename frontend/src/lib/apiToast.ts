import { toast } from 'sonner'
import { ApiRequestError } from '@/lib/api'

type Options = Readonly<{
  successMessage?: string
}>

/**
 * Wraps an async API call: on success optionally shows a sonner success toast;
 * on `ApiRequestError` shows the server's `detail` as a destructive toast.
 * Returns `true` if the call succeeded, `false` otherwise — callers can branch
 * on the result if they need to update local state.
 */
export async function withApiToast(
  fn: () => Promise<unknown>,
  { successMessage }: Options = {},
): Promise<boolean> {
  try {
    await fn()
    if (successMessage !== undefined) toast.success(successMessage)
    return true
  } catch (err) {
    const message = err instanceof ApiRequestError ? err.message : 'Request failed'
    toast.error(message)
    return false
  }
}
