import DashboardShell from "@/components/layout/DashboardShell";
import OrganizationAdminPage from "@/components/organization/OrganizationAdminPage";

export default function OrganizationAdminRoute() {
  return (
    <DashboardShell>
      <OrganizationAdminPage />
    </DashboardShell>
  );
}
