"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AccountServiceError, djangoAccountService, type AccountService, type AccountSnapshot, type ProfileUpdate } from "@/lib/account-service";

type AccountLoadState =
  | { status: "loading"; account: null; error: null }
  | { status: "loaded"; account: AccountSnapshot; error: null }
  | { status: "error"; account: null; error: string };

type AccountContextValue = {
  state: AccountLoadState;
  refresh: () => Promise<void>;
  acceptAuthenticatedAccount: (account: AccountSnapshot) => void;
  updateProfile: (input: ProfileUpdate) => Promise<AccountSnapshot>;
  signOut: () => Promise<void>;
  requestUpgrade: () => Promise<void>;
  actionError: string | null;
  clearActionError: () => void;
};

const AccountContext = createContext<AccountContextValue | null>(null);

export function useAccount(): AccountContextValue {
  const context = useContext(AccountContext);
  if (!context) throw new Error("useAccount must be used inside AccountProvider.");
  return context;
}

export default function AccountProvider({
  children,
  service = djangoAccountService,
}: {
  children: ReactNode;
  service?: AccountService;
}) {
  const [state, setState] = useState<AccountLoadState>({ status: "loading", account: null, error: null });
  const [actionError, setActionError] = useState<string | null>(null);
  const requestSequence = useRef(0);

  const loadAccount = useCallback(async () => {
    const sequence = ++requestSequence.current;
    try {
      const account = await service.getCurrentAccount();
      if (sequence === requestSequence.current) {
        setState({ status: "loaded", account, error: null });
      }
    } catch (error) {
      if (sequence !== requestSequence.current) return;
      const message = error instanceof AccountServiceError && (error.status === 401 || error.status === 403)
        ? "Your session has expired or could not be verified. Please sign in again."
        : error instanceof Error
          ? error.message
          : "Account information could not be loaded.";
      setState({
        status: "error",
        account: null,
        error: message,
      });
    }
  }, [service]);

  const refresh = useCallback(async () => {
    setState({ status: "loading", account: null, error: null });
    await loadAccount();
  }, [loadAccount]);

  const acceptAuthenticatedAccount = useCallback((account: AccountSnapshot) => {
    requestSequence.current += 1;
    setState({ status: "loaded", account, error: null });
  }, []);

  useEffect(() => {
    void Promise.resolve().then(loadAccount);
  }, [loadAccount]);

  const updateProfile = useCallback(async (input: ProfileUpdate) => {
    const sequence = ++requestSequence.current;
    try {
      const account = await service.updateProfile(input);
      if (sequence === requestSequence.current) {
        setState({ status: "loaded", account, error: null });
      }
      return account;
    } catch (error) {
      if (sequence === requestSequence.current && error instanceof AccountServiceError && (error.status === 401 || error.status === 403)) {
        setState({ status: "error", account: null, error: "Your session is no longer valid. Sign in again." });
      }
      throw error;
    }
  }, [service]);

  const signOut = useCallback(async () => {
    setActionError(null);
    try {
      await service.signOut();
      window.location.replace("/login?loggedOut=1");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Sign out failed. Your session may still be active.";
      setActionError(message);
      throw error;
    }
  }, [service]);

  const requestUpgrade = useCallback(async () => {
    setActionError(null);
    try {
      await service.requestUpgrade();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Upgrade is not connected.";
      setActionError(message);
      throw error;
    }
  }, [service]);

  const value = useMemo<AccountContextValue>(() => ({
    state,
    refresh,
    acceptAuthenticatedAccount,
    updateProfile,
    signOut,
    requestUpgrade,
    actionError,
    clearActionError: () => setActionError(null),
  }), [acceptAuthenticatedAccount, actionError, refresh, requestUpgrade, signOut, state, updateProfile]);

  return <AccountContext.Provider value={value}>{children}</AccountContext.Provider>;
}
