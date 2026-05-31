import { useState } from 'react'
import { Check, Copy } from 'lucide-react'

type Props = Readonly<{
  triggerId: string
  secret: string | null
}>

function CopyBlock({ label, text }: Readonly<{ label: string; text: string }>) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="space-y-1">
      <p className="text-[10px] text-muted-foreground font-semibold uppercase tracking-wider">
        {label}
      </p>
      <div className="flex items-center gap-2 bg-background rounded-lg px-3 py-2 border border-border">
        <code className="text-xs font-mono text-foreground flex-1 truncate">{text}</code>
        <button
          className="shrink-0 text-muted-foreground hover:text-foreground transition-colors"
          onClick={() => { handleCopy() }}
          aria-label={`Copy ${label}`}
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 text-emerald-500" />
          ) : (
            <Copy className="h-3.5 w-3.5" />
          )}
        </button>
      </div>
    </div>
  )
}

export default function WebhookSnippet({ triggerId, secret }: Props) {
  const baseUrl =
    typeof globalThis !== 'undefined' && 'location' in globalThis
      ? (globalThis as typeof globalThis & { location: { origin: string } }).location.origin
      : ''
  const url = `${baseUrl}/api/v1/triggers/${triggerId}/webhook`
  const bearer = secret ? `Bearer ${secret}` : '(secret not loaded)'

  return (
    <div className="space-y-3 p-4 bg-secondary/20 rounded-lg border border-border">
      <p className="text-xs text-muted-foreground">
        POST to this URL with an{' '}
        <code className="font-mono text-foreground">Authorization</code> header
        and a JSON body containing <code className="font-mono text-foreground">file_path</code>.
      </p>
      <CopyBlock label="Endpoint URL" text={url} />
      <CopyBlock label="Authorization Header" text={bearer} />
      <CopyBlock
        label="Example cURL"
        text={`curl -X POST "${url}" -H "Authorization: ${bearer}" -H "Content-Type: application/json" -d '{"file_path": "/media/TV/episode.mkv"}'`}
      />
    </div>
  )
}
