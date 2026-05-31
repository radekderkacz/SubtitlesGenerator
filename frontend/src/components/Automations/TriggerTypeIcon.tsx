import { Clock, FolderSearch, Webhook } from 'lucide-react'
import type { TriggerType } from '@/types/api'

type Props = Readonly<{
  type: TriggerType
  className?: string
}>

const TYPE_CONFIG: Record<TriggerType, { icon: React.ElementType; bg: string; text: string }> = {
  watch: { icon: FolderSearch, bg: 'bg-blue-500/20', text: 'text-blue-400' },
  cron: { icon: Clock, bg: 'bg-amber-500/20', text: 'text-amber-400' },
  webhook: { icon: Webhook, bg: 'bg-purple-500/20', text: 'text-purple-400' },
}

export default function TriggerTypeIcon({ type, className }: Props) {
  const { icon: Icon, bg, text } = TYPE_CONFIG[type]
  return (
    <div
      className={`w-10 h-10 rounded-lg flex items-center justify-center shrink-0 ${bg} ${text} ${className ?? ''}`}
      aria-hidden="true"
    >
      <Icon className="h-5 w-5" />
    </div>
  )
}
