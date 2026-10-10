import { notFound } from "next/navigation";
import QuotaManagement from "@/components/admin/QuotaManagement";

const sections = new Set(["users", "teams", "capacity", "policies"]);

export default async function QuotaSectionPage({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = await params;
  if (!sections.has(section)) notFound();
  return <QuotaManagement section={section} />;
}
