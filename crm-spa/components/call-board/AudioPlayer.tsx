"use client";

import { useEffect, useRef, useState } from "react";
import { useT } from "@/lib/i18n";
import { formatDuration } from "./kit";
import { fetchCallAudio, AudioError } from "./audio";

/**
 * AudioPlayer — Bearer-blob call recording player (§10.3/§10.11). The recording
 * is fetched lazily on first Play (the audio endpoint is Bearer-gated, so a
 * plain <audio src> can't reach it). Keyboard: Space play/pause, ←/→ ±5s (§13).
 * The endpoint is gated to MANAGE|ADMIN — for other roles the fetch 403s and we
 * show a neutral «нет доступа», never a red crash.
 */
export function AudioPlayer({ callId }: { callId: string }) {
  const t = useT();
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [ready, setReady] = useState(false);
  const [errorKey, setErrorKey] = useState<"forbidden" | "error" | null>(null);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [cur, setCur] = useState(0);
  const [dur, setDur] = useState(0);

  useEffect(() => {
    return () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    };
  }, []);

  async function ensureLoaded(): Promise<HTMLAudioElement | null> {
    if (ready && audioRef.current) return audioRef.current;
    setLoading(true);
    setErrorKey(null);
    try {
      const url = await fetchCallAudio(callId);
      urlRef.current = url;
      const el = new Audio(url);
      el.playbackRate = rate;
      el.addEventListener("timeupdate", () => setCur(el.currentTime));
      el.addEventListener("loadedmetadata", () => setDur(el.duration || 0));
      el.addEventListener("ended", () => setPlaying(false));
      audioRef.current = el;
      setReady(true);
      return el;
    } catch (e) {
      setErrorKey(e instanceof AudioError && e.code === "forbidden" ? "forbidden" : "error");
      return null;
    } finally {
      setLoading(false);
    }
  }

  async function toggle() {
    const el = await ensureLoaded();
    if (!el) return;
    if (el.paused) {
      await el.play().catch(() => setErrorKey("error"));
      setPlaying(true);
    } else {
      el.pause();
      setPlaying(false);
    }
  }

  function seek(delta: number) {
    const el = audioRef.current;
    if (!el) return;
    el.currentTime = Math.max(0, Math.min(el.duration || 0, el.currentTime + delta));
  }

  function seekTo(fraction: number) {
    const el = audioRef.current;
    if (!el || !el.duration) return;
    el.currentTime = fraction * el.duration;
  }

  function setSpeed(r: number) {
    setRate(r);
    if (audioRef.current) audioRef.current.playbackRate = r;
  }

  function onKey(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === " ") {
      e.preventDefault();
      void toggle();
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      seek(5);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      seek(-5);
    }
  }

  if (errorKey) {
    return (
      <div className="rounded-ctl border border-hair2 bg-surface px-4 py-3 text-[13px] text-steel">
        {errorKey === "forbidden" ? t("callsboard.audio.forbidden") : t("callsboard.audio.error")}
      </div>
    );
  }

  const frac = dur > 0 ? cur / dur : 0;

  return (
    <div
      className="flex items-center gap-3 rounded-ctl border border-hair2 bg-surface px-3 py-2.5"
      tabIndex={0}
      onKeyDown={onKey}
      role="group"
      aria-label={t("callsboard.audio.player")}
    >
      <button
        type="button"
        onClick={toggle}
        aria-label={playing ? t("callsboard.audio.pause") : t("callsboard.audio.play")}
        className="grid h-9 w-9 flex-none place-items-center rounded-full bg-ink text-white hover:bg-slate cursor-pointer disabled:opacity-50"
        disabled={loading}
      >
        {playing ? "❚❚" : "▶"}
      </button>

      <button
        type="button"
        className="relative h-2 flex-1 rounded-full bg-hair2 cursor-pointer"
        aria-label={t("callsboard.audio.seek")}
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          seekTo((e.clientX - rect.left) / rect.width);
        }}
      >
        <span
          className="absolute left-0 top-0 h-full rounded-full bg-primary"
          style={{ width: `${Math.round(frac * 100)}%` }}
        />
      </button>

      <span className="font-mono text-[12px] text-steel whitespace-nowrap">
        {loading ? t("callsboard.audio.loading") : `${formatDuration(cur)} / ${formatDuration(dur)}`}
      </span>

      <div className="flex flex-none gap-1">
        {[1, 1.5].map((r) => (
          <button
            key={r}
            type="button"
            onClick={() => setSpeed(r)}
            className={
              "rounded px-2 py-1 text-[12px] font-mono cursor-pointer " +
              (rate === r ? "bg-ink text-white" : "text-steel hover:text-primary")
            }
          >
            {r}x
          </button>
        ))}
      </div>
    </div>
  );
}
