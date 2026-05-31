import { useEffect, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import ConfirmDialog from "@/components/ConfirmDialog/ConfirmDialog";
import SrtBadge from "@/components/FileBrowser/SrtBadge";
import { ApiRequestError, apiFetch, submitJob } from "@/lib/api";
import type { FileBrowseEntry, Settings } from "@/types/api";
import GenerationControls, {
  useGenerationControlsState,
  controlsBlockedReason,
  buildJobPayload,
} from "./GenerationControls";

type Props = Readonly<{
  file: FileBrowseEntry | null;
  fullPath: string | null;
}>;

/**
 * Persistent right-rail Generation Settings panel for the Library page (the
 * desktop equivalent of SubmitSheet, per the design).
 *
 * Renders an empty state when no file is selected so the rail visually
 * holds its place in the 3-column layout. Submitting routes the user to
 * the Active Queue and toasts the standard "processing continues" copy.
 */
export default function GenerationPanel({ file, fullPath }: Props) {
  const navigate = useNavigate();

  const settingsQuery = useQuery({
    queryKey: ["settings"],
    queryFn: () => apiFetch<Settings>("/api/v1/settings"),
  });

  const { values, onChange, reset } = useGenerationControlsState();
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [confirmRegenerateOpen, setConfirmRegenerateOpen] =
    useState<boolean>(false);

  const profiles = settingsQuery.data?.profiles ?? [];

  // Reseed defaults whenever the selected file changes — keeps the panel
  // honest if the user adjusts settings between picks.
  useEffect(() => {
    if (!file) return;
    reset();
  }, [file]);

  const filename = file?.name ?? null;
  const hasSrt = file?.has_srt ?? false;

  const blockedReason = controlsBlockedReason(values, profiles.length);
  const isSubmitDisabled = submitting || blockedReason !== null;

  const doSubmit = async () => {
    if (fullPath === null) return;
    setSubmitting(true);
    try {
      await submitJob(buildJobPayload(fullPath, values));
      toast.success("Processing continues even if you close this tab.", {
        duration: 4000,
      });
      navigate("/");
    } catch (err) {
      const message =
        err instanceof ApiRequestError ? err.message : "Submission failed";
      toast.error(message);
    } finally {
      setSubmitting(false);
    }
  };

  const handlePrimary = () => {
    if (hasSrt) {
      setConfirmRegenerateOpen(true);
      return;
    }
    void doSubmit();
  };

  const primaryLabel = hasSrt ? "Regenerate" : "Generate Subtitles";

  if (!file) {
    return (
      <aside
        aria-label="Generation Settings"
        className="w-[380px] shrink-0 border-l border-border bg-popover hidden xl:flex flex-col"
      >
        <header className="p-6 border-b border-border">
          <h2 className="text-base font-semibold text-foreground">
            Generation Settings
          </h2>
          <p className="text-xs text-muted-foreground mt-1">
            Pick a file from the list to configure subtitle generation.
          </p>
        </header>
      </aside>
    );
  }

  return (
    <>
      <aside
        aria-label={`Generation Settings: ${filename}`}
        className="w-[380px] shrink-0 border-l border-border bg-popover hidden xl:flex flex-col shadow-[-10px_0_30px_rgba(0,0,0,0.2)]"
      >
        <header className="p-6 border-b border-border">
          <h2 className="text-base font-semibold text-foreground">
            Generation Settings
          </h2>
          <p className="text-xs text-muted-foreground mt-1 break-all font-mono">
            {filename}
          </p>
          <div className="mt-2">
            <SrtBadge hasSrt={hasSrt} />
          </div>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
          <GenerationControls
            idPrefix="gp"
            values={values}
            profiles={profiles}
            onChange={onChange}
          />
        </div>

        <footer className="p-6 border-t border-border bg-popover">
          <Button
            onClick={handlePrimary}
            disabled={isSubmitDisabled}
            className="w-full gap-2 bg-[var(--action-accent)] hover:bg-[var(--action-accent)]/90 text-white font-semibold py-3 rounded-lg shadow-[0_0_20px_rgba(59,130,246,0.3)]"
          >
            {submitting ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Sparkles className="h-4 w-4" aria-hidden="true" />
            )}
            <span className="text-sm">
              {submitting ? "Submitting…" : primaryLabel}
            </span>
          </Button>
        </footer>
      </aside>

      <ConfirmDialog
        open={confirmRegenerateOpen}
        onOpenChange={setConfirmRegenerateOpen}
        title={`Regenerate subtitles for ${filename}?`}
        description="An SRT already exists for this file. Regenerating will overwrite it on the next worker run."
        confirmLabel="Regenerate"
        onConfirm={doSubmit}
        destructive
      />
    </>
  );
}
