"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { fetchRecordingUrl, cardErrorText } from "./data";

/**
 * Recording playback — only mounted for RECORDING_ROLES (risk_officer / heads /
 * director / super_admin). The stream is auth-gated on the Flask adapter, so we
 * fetch it with the bearer token into a blob URL (a plain <audio src> can't carry
 * the header). The adapter also writes the recording_listen audit row.
 */
export function RecordingPlayer({ callId }: { callId: string }) {
  const t = useT();
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    return () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    };
  }, []);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const objUrl = await fetchRecordingUrl(callId);
      urlRef.current = objUrl;
      setUrl(objUrl);
    } catch (e) {
      setError(cardErrorText(e, t, "card.recording.unavailable"));
    } finally {
      setLoading(false);
    }
  }

  if (url) {
    return <audio controls src={url} className="h-8 w-full max-w-[260px]" />;
  }

  return (
    <div className="flex items-center gap-2">
      <Button size="sm" variant="ghost" onClick={load} loading={loading}>
        {t("card.recording.playButton")}
      </Button>
      {error ? <span className="text-[12px] text-neg">{error}</span> : null}
    </div>
  );
}
