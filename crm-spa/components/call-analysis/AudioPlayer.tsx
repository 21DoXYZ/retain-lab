"use client";

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { useT } from "@/lib/i18n";
import { Spinner } from "@/components/ui";
import { fetchAudioUrl } from "./data";
import { formatSec } from "./timecode";

/**
 * Плеер карточки (§10.3, снизу sticky). Запись тянется Bearer-fetch'ем в blob
 * (заголовок в <audio src> не положить). Управление: play/pause, seek, 1.0x/1.5x
 * и клавиши (обрабатывает CallCardScreen). seek()/toggle() открыты наружу через
 * ref — это перемотка «моста доказательств»: клик по критерию → на эту секунду.
 */
export interface AudioPlayerHandle {
  seek: (sec: number) => void;
  toggle: () => void;
  /** Перемотка на delta секунд от текущей (клавиши ←/→ ±5с, §10.3). */
  nudge: (delta: number) => void;
}

interface AudioPlayerProps {
  callId: string;
}

const SPEEDS = [1, 1.5] as const;

export const AudioPlayer = forwardRef<AudioPlayerHandle, AudioPlayerProps>(function AudioPlayer(
  { callId },
  ref,
) {
  const t = useT();
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const pendingSeekRef = useRef<number | null>(null);

  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [cur, setCur] = useState(0);
  const [dur, setDur] = useState(0);
  const [speed, setSpeed] = useState<number>(1);

  // Blob запись под текущий звонок; чистим предыдущий URL при смене id/размонтаже.
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(false);
    setPlaying(false);
    setCur(0);
    setDur(0);
    fetchAudioUrl(callId)
      .then((objUrl) => {
        if (!alive) {
          URL.revokeObjectURL(objUrl);
          return;
        }
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        urlRef.current = objUrl;
        setUrl(objUrl);
      })
      .catch(() => {
        if (alive) setError(true);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [callId]);

  useEffect(() => {
    return () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    };
  }, []);

  const applySeek = useCallback((sec: number) => {
    const el = audioRef.current;
    if (!el) return;
    if (!Number.isFinite(el.duration) || el.duration === 0) {
      pendingSeekRef.current = sec; // метаданные ещё не загружены — отложим
      return;
    }
    el.currentTime = Math.max(0, Math.min(sec, el.duration));
  }, []);

  const toggle = useCallback(() => {
    const el = audioRef.current;
    if (!el) return;
    if (el.paused) void el.play().catch(() => undefined);
    else el.pause();
  }, []);

  useImperativeHandle(
    ref,
    () => ({
      seek: (sec: number) => {
        applySeek(sec);
        const el = audioRef.current;
        if (el && el.paused) void el.play().catch(() => undefined); // §10.3: слышит момент
      },
      toggle,
      nudge: (delta: number) => {
        const el = audioRef.current;
        if (el) applySeek((el.currentTime || 0) + delta);
      },
    }),
    [applySeek, toggle],
  );

  function onLoadedMetadata() {
    const el = audioRef.current;
    if (!el) return;
    setDur(Number.isFinite(el.duration) ? el.duration : 0);
    if (pendingSeekRef.current != null) {
      applySeek(pendingSeekRef.current);
      pendingSeekRef.current = null;
    }
  }

  function cycleSpeed() {
    const idx = SPEEDS.indexOf(speed as (typeof SPEEDS)[number]);
    const next = SPEEDS[(idx + 1) % SPEEDS.length];
    setSpeed(next);
    if (audioRef.current) audioRef.current.playbackRate = next;
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-[13px] text-steel">
        <Spinner size={16} /> {t("calls.audio.loading")}
      </div>
    );
  }
  if (error || !url) {
    return <div className="text-[13px] text-neg">{t("calls.audio.unavailable")}</div>;
  }

  return (
    <div className="flex items-center gap-3">
      <audio
        ref={audioRef}
        src={url}
        onLoadedMetadata={onLoadedMetadata}
        onTimeUpdate={() => setCur(audioRef.current?.currentTime ?? 0)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
      />
      <button
        type="button"
        onClick={toggle}
        aria-label={playing ? t("calls.audio.pause") : t("calls.audio.play")}
        className="grid place-items-center w-9 h-9 flex-none rounded-full bg-ink text-white hover:bg-slate transition-colors cursor-pointer"
      >
        {playing ? "❚❚" : "▶"}
      </button>

      <input
        type="range"
        min={0}
        max={dur || 0}
        step={0.1}
        value={cur}
        onChange={(e) => applySeek(Number(e.target.value))}
        aria-label={t("calls.transcript.title")}
        className="flex-1 accent-primary cursor-pointer"
      />

      <span className="font-mono text-[12.5px] text-slate tabular-nums whitespace-nowrap">
        {formatSec(cur)} / {formatSec(dur)}
      </span>

      <button
        type="button"
        onClick={cycleSpeed}
        className="font-mono text-[12.5px] px-2 py-1 rounded-ctl border border-hair2 text-slate hover:border-primary hover:text-primary transition-colors cursor-pointer"
      >
        {speed.toFixed(1)}x
      </button>
    </div>
  );
});
