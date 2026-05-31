import { CheckCircle2 } from "lucide-react"
import { Input } from "@/components/ui/input"

type Props = Readonly<{
  id: string
  value: string
  onChange: (value: string) => void
  error?: string
  success?: boolean
  placeholder?: string
}>

function PathInput({ id, value, onChange, error, success, placeholder }: Props) {
  return (
    <div className="flex flex-col gap-1">
      <div className="relative flex items-center">
        <Input
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          aria-invalid={!!error}
          aria-describedby={error ? `${id}-error` : undefined}
          className="pr-10 font-mono text-sm"
        />
        {success && (
          <CheckCircle2 aria-hidden="true" className="absolute right-2 h-4 w-4 text-emerald-500 pointer-events-none" />
        )}
      </div>
      {error && <p id={`${id}-error`} className="text-sm text-destructive">{error}</p>}
    </div>
  )
}

export { PathInput }
