import DashboardShell from "@/components/layout/DashboardShell";

export default function Home() {
  return (
    <DashboardShell>
      <section className="m-6 min-h-[calc(100%-48px)] rounded-[28px] bg-[#E9EDF4] p-8">
        <h1 className="text-2xl font-semibold tracking-tight text-[#121523]">
          My Drive
        </h1>

        <p className="mt-1 text-[14px] text-[#71809A]">
          Manage your files securely.
        </p>
      </section>
    </DashboardShell>
  );
}