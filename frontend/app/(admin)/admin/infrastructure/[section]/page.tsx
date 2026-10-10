import InfrastructureDetail from "@/components/admin/InfrastructureDetail";

export default async function InfrastructureSectionPage({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = await params;
  return <InfrastructureDetail section={section} />;
}
