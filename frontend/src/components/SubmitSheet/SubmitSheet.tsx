import { useEffect, useState } from "react";
import { Info, Loader2, Sparkles } from "lucide-react";
import { useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import ConfirmDialog from "@/components/ConfirmDialog/ConfirmDialog";
import GenerationControls, {
  controlsBlockedReason,
  buildJobPayload,
  useGenerationControlsState,
} from "./GenerationControls";
import SrtBadge from "@/components/FileBrowser/SrtBadge";
import { ApiRequestError, apiFetch, submitJob } from "@/lib/api";
import type { FileBrowseEntry, Settings } from "@/types/api";

type Props = Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  file: FileBrowseEntry | null;
  fullPath: string | null;
}>;

export default function SubmitSheet({
  open,
  onOpenChange,
  file,
  fullPath,
}: Props) {
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

  // Re-seed defaults from settings every time the sheet (re)opens for a file.
  useEffect(() => {
    if (!open) return;
    reset();
  }, [open]);

  const filename = file?.name ?? "";
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
      onOpenChange(false);
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

  return (
    <>
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent
          side="right"
          className="w-[400px] sm:max-w-md flex flex-col"
        >
          <SheetHeader>
            <SheetTitle className="font-mono text-base break-all">
              {filename || "No file selected"}
            </SheetTitle>
            <SheetDescription className="flex items-center gap-2">
              <SrtBadge hasSrt={hasSrt} />
              {fullPath && (
                <span className="text-xs font-mono text-muted-foreground truncate">
                  {fullPath}
                </span>
              )}
            </SheetDescription>
          </SheetHeader>

          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-6">
            <GenerationControls
              idPrefix="ss"
              values={values}
              profiles={profiles}
              existingSubsDefault={settingsQuery.data?.prefer_existing_subs ?? true}
              onChange={onChange}
              onProfileLinkClick={() => onOpenChange(false)}
            />

            {/* Primary CTA sits directly under the controls (right below the AI
                Profile selector), consistent with the desktop GenerationPanel,
                rather than pinned in a bottom footer. */}
            <div className="flex flex-col gap-3 pt-2">
              <Button
                onClick={handlePrimary}
                disabled={isSubmitDisabled}
                className="w-full gap-2 bg-[var(--action-accent)] hover:bg-[var(--action-accent)]/90 text-white font-semibold py-6 rounded-lg shadow-[0_0_15px_rgba(59,130,246,0.3)] text-sm uppercase tracking-wider"
              >
                {submitting ? (
                  <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" />
                ) : (
                  <Sparkles className="h-5 w-5" aria-hidden="true" />
                )}
                <span>{submitting ? "Submitting…" : primaryLabel}</span>
              </Button>
              <div className="flex items-start gap-2 text-xs text-muted-foreground bg-secondary/40 border border-border rounded-md p-3">
                <Info className="h-4 w-4 shrink-0 mt-0.5" aria-hidden="true" />
                <span>Processing continues even if you close this tab.</span>
              </div>
              <button
                type="button"
                onClick={() => onOpenChange(false)}
                disabled={submitting}
                className="text-xs font-semibold uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </SheetContent>
      </Sheet>

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
