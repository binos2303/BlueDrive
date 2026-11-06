/** UI validation is advisory; Django is the authorization boundary. */
export type AdminFileAction = "trash" | "restore" | "purge";
export type AdminFileLifecycle = "active" | "trash";

export function actionsForAdminFile(lifecycle: AdminFileLifecycle, canManage: boolean): AdminFileAction[] {
  if (!canManage) return [];
  return lifecycle === "active" ? ["trash"] : ["restore", "purge"];
}

export function canSubmitAdminFileAction(input: {
  action: AdminFileAction;
  reason: string;
  fileName: string;
  confirmation: string;
}): boolean {
  const reason = input.reason.trim();
  return reason.length >= 8 && reason.length <= 500 &&
    (input.action !== "purge" || input.fileName === input.confirmation);
}
