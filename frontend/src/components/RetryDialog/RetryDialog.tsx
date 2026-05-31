import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'

type Props = Readonly<{
  open: boolean
  onOpenChange: (open: boolean) => void
  filename: string
  onRetry: () => unknown
}>

export default function RetryDialog({
  open,
  onOpenChange,
  filename,
  onRetry,
}: Props) {
  const close = () => onOpenChange(false)
  const submit = async () => {
    await onRetry()
    close()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{`Retry ${filename}?`}</DialogTitle>
          <DialogDescription>
            A new job will be queued using your <strong>current Settings</strong>{' '}
            (transcription + translation models). The failed job stays in the
            list for reference.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="flex-col-reverse sm:flex-row sm:justify-end gap-2">
          <Button variant="outline" onClick={close}>
            Keep
          </Button>
          <Button onClick={submit}>Retry</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
