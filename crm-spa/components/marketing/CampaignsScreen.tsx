"use client";

import Link from "next/link";
import { PageHeader, Card } from "@/components/ui";
import { formatInt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useFlaskData } from "./useFlaskData";
import type { CampaignsResponse, CampaignSegment } from "./types";

function SegmentCard({ seg }: { seg: CampaignSegment }) {
  const t = useT();
  return (
    <Card className="flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div className="font-semibold text-[15px]">
          <span className="mr-1.5">{seg.icon}</span>
          {seg.name}
        </div>
        <div className="text-[20px] font-extrabold text-primary tracking-[-0.5px] whitespace-nowrap">
          {formatInt(seg.count)}
          <span className="text-[12px] font-normal text-steel"> {t("marketing.campaigns.playersSuffix")}</span>
        </div>
      </div>
      <div className="text-[13px] text-steel leading-snug">{seg.who}</div>
      <div className="text-[13px] leading-snug">💡 {t("marketing.campaigns.offerPrefix")} {seg.offer}</div>
      <Link
        href={`/players?seg=${encodeURIComponent(seg.key)}`}
        className="text-primary text-[13px] font-medium hover:underline mt-1"
      >
        {t("marketing.campaigns.playersListLink")}
      </Link>
    </Card>
  );
}

function CardSkeleton() {
  return <div className="min-h-[148px] rounded-card border border-hair bg-canvas animate-pulse" />;
}

export function CampaignsScreen() {
  const t = useT();
  const { state, data, error, reload } = useFlaskData<CampaignsResponse>("/api/v1/campaigns");
  const loading = state === "loading";

  return (
    <>
      <PageHeader
        title={<>{t("marketing.campaigns.title")}</>}
        lead={t("marketing.campaigns.lead")}
      />

      {state === "error" ? (
        <Card className="mt-5">
          <div className="text-neg text-[13.5px]">{error}</div>
          <button onClick={reload} className="mt-2 text-primary text-[13px] underline">
            {t("common.retry")}
          </button>
        </Card>
      ) : (
        <div className="mt-5 grid gap-4 grid-cols-1 md:grid-cols-2 xl:grid-cols-3">
          {loading
            ? Array.from({ length: 8 }).map((_, i) => <CardSkeleton key={i} />)
            : (data?.segments ?? []).map((seg) => <SegmentCard key={seg.key} seg={seg} />)}
        </div>
      )}
    </>
  );
}
