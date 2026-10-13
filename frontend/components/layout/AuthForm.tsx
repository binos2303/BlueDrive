"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { ArrowRight, Cloud, Eye, EyeOff } from "lucide-react";
import { useAccount } from "@/components/account/AccountProvider";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import { AccountServiceError } from "@/lib/account-service";
import { djangoAuthService } from "@/lib/auth-service";
import { safeInternalRedirect } from "@/lib/auth-redirect";

export default function AuthForm({ mode }: { mode: "login" | "register" }) {
  const isRegister = mode === "register";
  const passwordFieldName = isRegister ? "password1" : "password";
  const router = useRouter();
  const { acceptAuthenticatedAccount } = useAccount();
  const [showPassword, setShowPassword] = useState(false);
  const [message, setMessage] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [pending, setPending] = useState(false);
  const [registrationAccepted, setRegistrationAccepted] = useState(false);

  function fieldError(name: string) {
    return fieldErrors[name]?.join(" ") ?? "";
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    setFieldErrors({});
    setRegistrationAccepted(false);
    setPending(true);
    const formData = new FormData(event.currentTarget);
    try {
      if (isRegister) {
        await djangoAuthService.register({
            username: String(formData.get("username") ?? "").trim(),
            email: String(formData.get("email") ?? "").trim(),
            password1: String(formData.get("password1") ?? ""),
            password2: String(formData.get("password2") ?? ""),
          });
        setRegistrationAccepted(true);
        setMessage(
          "If registration can be completed, you can sign in to continue. If you cannot sign in, check your details or contact support.",
        );
        return;
      }
      const account = await djangoAuthService.signIn({
        email: String(formData.get("email") ?? "").trim(),
        password: String(formData.get(passwordFieldName) ?? ""),
      });
      acceptAuthenticatedAccount(account);
      const next = new URLSearchParams(window.location.search).get("next");
      router.replace(safeInternalRedirect(next));
    } catch (error) {
      if (error instanceof AccountServiceError) {
        setFieldErrors(error.fieldErrors);
        setMessage(
          error.status === 401
            ? "Invalid email or password."
            : error.status === 403
              ? "Your session could not be confirmed. Refresh and try again."
              : error.message,
        );
      } else {
        setMessage("Authentication failed. Please try again.");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-5 py-12 sm:px-8">
      <section className="w-full max-w-[500px] rounded-3xl border border-border bg-surface p-7 shadow-[var(--shadow-popover)] sm:p-10" aria-labelledby="auth-title">
        <Link href="/login" className="mb-8 flex w-fit items-center gap-3 rounded-md">
          <span className="flex h-10 w-10 items-center justify-center rounded-[var(--radius-control)] bg-brand text-white"><Cloud size={20} /></span>
          <span className="text-lg font-semibold text-foreground">BlueDrive</span>
        </Link>

        <p className="text-sm font-semibold uppercase tracking-[0.12em] text-brand-contrast">{isRegister ? "Create account" : "Welcome back"}</p>
        <h1 id="auth-title" className="mt-3 text-3xl font-semibold tracking-tight text-foreground">
            {isRegister ? "Start your secure workspace" : "Sign in to BlueDrive"}
        </h1>
        <p className="mt-2 text-sm leading-6 text-muted">
          {isRegister ? "Create an account to store and manage your files securely." : "Enter your email and password to access your files."}
        </p>

        <div className="mt-6 flex items-center gap-3 text-xs text-muted" aria-hidden="true">
          <div className="h-px flex-1 bg-border" />
          <span>Continue with email</span>
          <div className="h-px flex-1 bg-border" />
        </div>

        <form className="mt-6 space-y-4" onSubmit={submit}>
            {isRegister && (
              <label className="block">
                <span className="mb-2 block text-sm font-medium text-foreground">Username</span>
                <Input
                  required
                  disabled={pending}
                  name="username"
                  autoComplete="username"
                  placeholder="Choose a username"
                  invalid={Boolean(fieldError("username"))}
                  aria-describedby={fieldError("username") ? "username-error" : undefined}
                  className="h-12 px-4"
                />
                {fieldError("username") && <span id="username-error" className="mt-1 block text-xs text-danger">{fieldError("username")}</span>}
              </label>
            )}

            <label className="block">
              <span className="mb-2 block text-sm font-medium text-foreground">Email address</span>
              <Input
                required
                disabled={pending}
                name="email"
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
                invalid={Boolean(fieldError("email"))}
                aria-describedby={fieldError("email") ? "email-error" : undefined}
                className="h-12 px-4"
              />
              {fieldError("email") && <span id="email-error" className="mt-1 block text-xs text-danger">{fieldError("email")}</span>}
            </label>

            <label className="block">
              <span className="mb-2 block text-sm font-medium text-foreground">Password</span>
              <span className="relative block">
                <Input
                  required
                  disabled={pending}
                  name={passwordFieldName}
                  minLength={8}
                  type={showPassword ? "text" : "password"}
                  autoComplete={isRegister ? "new-password" : "current-password"}
                  placeholder={isRegister ? "At least 8 characters" : "Enter your password"}
                  invalid={Boolean(fieldError(passwordFieldName))}
                  aria-describedby={fieldError(passwordFieldName) ? `${passwordFieldName}-error` : undefined}
                  className="h-12 px-4 pr-12"
                />
                <button
                  type="button"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-muted hover:bg-background"
                >
                  {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                </button>
              </span>
              {fieldError(passwordFieldName) && <span id={`${passwordFieldName}-error`} className="mt-1 block text-xs text-danger">{fieldError(passwordFieldName)}</span>}
            </label>

            {isRegister && (
              <label className="block">
                <span className="mb-2 block text-sm font-medium text-foreground">Confirm password</span>
                <Input
                  required
                  disabled={pending}
                  name="password2"
                  minLength={8}
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  placeholder="Enter your password again"
                  invalid={Boolean(fieldError("password2"))}
                  aria-describedby={fieldError("password2") ? "password2-error" : undefined}
                  className="h-12 px-4"
                />
                {fieldError("password2") && <span id="password2-error" className="mt-1 block text-xs text-danger">{fieldError("password2")}</span>}
              </label>
            )}

            {!isRegister && (
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted">Password recovery is not available yet.</span>
              </div>
            )}

            {message && <p role={registrationAccepted ? "status" : "alert"} className={`rounded-[var(--radius-control)] border p-3 text-sm leading-5 ${registrationAccepted ? "border-success/20 bg-success/10 text-success" : "border-danger/20 bg-danger/10 text-danger"}`}>{message}</p>}

            <Button type="submit" variant="primary" size="lg" loading={pending} className="w-full">
              {pending ? "Please wait…" : isRegister ? "Create account" : "Sign in"}
              {!pending && <ArrowRight size={17} aria-hidden="true" />}
            </Button>
          </form>

          <p className="mt-7 text-center text-sm text-muted">
            {isRegister ? "Already have an account?" : "Don't have an account?"}{" "}
            <Link href={isRegister ? "/login" : "/register"} className="rounded-sm font-semibold text-brand-contrast hover:text-brand-dark">
              {isRegister ? "Sign in" : "Create account"}
            </Link>
          </p>

      </section>
    </main>
  );
}
