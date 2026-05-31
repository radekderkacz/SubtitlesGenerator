import { useState } from "react";
import { Send, Loader2 } from "lucide-react";
import { useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import GenerationControls, {
  controlsBlockedReason,
  buildJobPayload,
  useGenerationControlsState,
} from "@/components/SubmitSheet/GenerationControls";
import { apiFetch, submitJob } from "@/lib/api";
import { withApiToast } from "@/lib/apiToast";
import type { Settings, FileBrowseEntry } from "@/types/api";

type Props = Readonly<{
  selectedPaths: ReadonlyArray<string>;
  /** Per-path metadata for the `has_srt` skip toggle. */
  fileIndex: ReadonlyMap<string, FileBrowseEntry>;
  onCleared: () => void;
}>;

/**
 * Sticky bottom action bar that appears when the user has selected ≥1 file
 * in the FileList. Submits a job per selected path through the existing
 * POST /api/v1/jobs endpoint — the worker is single-concurrency so they
 * naturally line up in the queue.
 *
 * The source/translate/target/profile controls come from the shared
 * `GenerationControls` cluster so the batch path applies the *same*
 * settings (uniformly) to every ticked file — translation included.
 */
export default function BatchActionBar({
  selectedPaths,
  fileIndex,
  onCleared,
}: Props) {
  const navigate = useNavigate();
  const { values, onChange } = useGenerationControlsState();
  const [skipExisting, setSkipExisting] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: () => apiFetch<Settings>("/api/v1/settings"),
  });

  const profiles = settings?.profiles ?? [];

  const eligiblePaths = skipExisting
    ? selectedPaths.filter((p) => !fileIndex.get(p)?.has_srt)
    : [...selectedPaths];
  const skippedCount = selectedPaths.length - eligiblePaths.length;
  const blockedReason = controlsBlockedReason(values, profiles.length);

  const handleSubmit = async () => {
    if (blockedReason !== null || eligiblePaths.length === 0) return;
    setIsSubmitting(true);
    let succeeded = 0;
    let failed = 0;
    for (const fullPath of eligiblePaths) {
      // Pass no successMessage so withApiToast stays silent on success — we
      // emit a single summary toast at the end. Per-file errors still surface.
      const ok = await withApiToast(() =>
        submitJob(buildJobPayload(fullPath, values)),
      );
      if (ok) succeeded += 1;
      else failed += 1;
    }
    setIsSubmitting(false);
    if (succeeded > 0 || failed === 0) {
      const tail = failed > 0 ? ` (${failed} failed)` : "";
      // Final summary toast — withApiToast was silent on success above.
      // Deferred import: keeps sonner out of this component's module graph
      // until the rare batch-summary path actually runs.
      const { toast } = await import("sonner");
      toast(`Queued ${succeeded} job${succeeded === 1 ? "" : "s"}${tail}`);
    }
    onCleared();
    // Mirror the single-file SubmitSheet flow: jump the user to the Active
    // Queue so they immediately see the work they just queued (and the
    // per-row cancel X on each row). Only on a real success — leaving the
    // user on Library is the right behaviour when nothing was queued.
    if (succeeded > 0) navigate("/");
  };

  return (
    <section
      aria-label="Batch submission"
      className="fixed bottom-0 right-0 left-64 z-30 bg-card border-t border-border shadow-[0_-10px_30px_rgba(0,0,0,0.3)] px-6 py-4"
    >
      <div className="max-w-[1280px] mx-auto flex flex-wrap items-start gap-6">
        <div className="flex-1 min-w-[260px] space-y-3">
          <p className="text-sm font-semibold text-foreground">
            {selectedPaths.length} file{selectedPaths.length === 1 ? "" : "s"}{" "}
            selected
          </p>

          <GenerationControls
            idPrefix="batch"
            values={values}
            profiles={profiles}
            onChange={onChange}
          />

          <label className="flex items-center gap-2 text-sm text-foreground cursor-pointer select-none">
            <input
              type="checkbox"
              checked={skipExisting}
              onChange={(e) => setSkipExisting(e.target.checked)}
              className="h-4 w-4 accent-primary"
            />
            <span>Skip files with SRT</span>
          </label>

          {skipExisting && skippedCount > 0 && (
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer text-amber-500">
                {skippedCount} of {selectedPaths.length} skipped — already have
                subtitles
              </summary>
              <ul className="mt-1 ml-4 list-disc">
                {selectedPaths
                  .filter((p) => fileIndex.get(p)?.has_srt)
                  .map((p) => (
                    <li key={p} className="font-mono">
                      {p.split("/").pop()}
                    </li>
                  ))}
              </ul>
            </details>
          )}
        </div>

        <div className="flex flex-col items-end gap-2">
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              onClick={onCleared}
              disabled={isSubmitting}
              // "Clear" (not "Cancel"): this empties the ticked selection;
              // it does NOT cancel running jobs. "Cancel" next to "Submit"
              // was being read as "cancel everything I just submitted".
              // Per-job cancellation lives on each row's X in the queue.
            >
              Clear
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={
                isSubmitting ||
                eligiblePaths.length === 0 ||
                blockedReason !== null
              }
              className="gap-2"
            >
              {isSubmitting ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Send className="h-4 w-4" aria-hidden="true" />
              )}
              Submit {eligiblePaths.length}
            </Button>
          </div>
          {blockedReason !== null && (
            <p className="text-xs text-muted-foreground">{blockedReason}</p>
          )}
        </div>
      </div>
    </section>
  );
}
