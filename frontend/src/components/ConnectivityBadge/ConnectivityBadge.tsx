export type ConnectivityStatus = 'idle' | 'testing' | 'ok' | 'failed'

type Props = Readonly<{
  status: ConnectivityStatus
  detail?: string
}>

export default function ConnectivityBadge({ status, detail }: Props) {
  if (status === 'idle') {
    return <span />
  }
  if (status === 'testing') {
    return <span className="text-sm text-amber-500">Testing…</span>
  }
  if (status === 'ok') {
    return (
      <span className="text-sm text-emerald-500">
        {detail ?? 'Connected'}
      </span>
    )
  }
  return (
    <span className="text-sm text-red-500">
      {`Failed — ${detail ?? 'Unknown error'}`}
    </span>
  )
}
