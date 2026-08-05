import { requireSegmentationRole } from "@/components/segmentation/guard";
import { OnboardingView } from "@/components/saas/OnboardingView";

/** /onboarding — визард Get started: 4 шага подключения с живыми статусами. */
export const dynamic = "force-dynamic";

export default async function OnboardingPage() {
  await requireSegmentationRole();
  return <OnboardingView />;
}
