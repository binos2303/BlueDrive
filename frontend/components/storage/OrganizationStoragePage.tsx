"use client";

import { useAccount } from "@/components/account/AccountProvider";
import StorageManager from "./StorageManager";

export default function OrganizationStoragePage() {
  const { state } = useAccount();
  if (state.status !== "loaded") return <p role="status" className="p-6 text-sm text-muted">Loading organization…</p>;
  const account = state.account?.account;
  if (account?.type !== "business" || !account.tenant) return <div className="p-6"><h1 className="text-2xl font-semibold">Organization storage</h1><p className="mt-3 text-sm text-muted">Select a business organization with delegated storage access to continue.</p></div>;
  return <div className="mx-auto w-full max-w-7xl p-4 sm:p-6"><StorageManager key={account.tenant.id} tenantId={account.tenant.id} /></div>;
}
