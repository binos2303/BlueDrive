"use client";
import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Cloud, Code2, Eye, EyeOff, Globe, MessageSquare } from "lucide-react";

const providers = [
  { name: "Google", icon: Globe, className: "border-[#E5E7EB] text-[#1F2937] hover:bg-[#F9FAFB]" },
  { name: "Facebook", icon: MessageSquare, className: "border-[#E5E7EB] text-[#1F2937] hover:bg-[#F9FAFB]" },
  { name: "GitHub", icon: Code2, className: "border-[#E5E7EB] text-[#1F2937] hover:bg-[#F9FAFB]" },
];

export default function AuthForm({ mode }: { mode: "login" | "register" }) {
  const isRegister = mode === "register";
  const [showPassword, setShowPassword] = useState(false);
  const [message, setMessage] = useState("");

  return (
    <main className="flex min-h-screen items-center justify-center bg-[#F6F8FC] px-5 py-12 sm:px-8">
        <div className="w-full max-w-[500px] rounded-[26px] bg-white/85 p-7 shadow-[0_18px_50px_rgba(18,21,35,0.08)] backdrop-blur-sm sm:p-10">
          <Link href="/login" className="mb-8 flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-[13px] bg-[#7188F9] text-white"><Cloud size={20} /></span>
            <span className="text-lg font-semibold">BlueDrive</span>
          </Link>

          <p className="text-sm font-semibold uppercase tracking-[0.12em] text-[#7188F9]">{isRegister ? "Create account" : "Welcome back"}</p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight text-[#121523]">
            {isRegister ? "Start your secure workspace" : "Sign in to BlueDrive"}
          </h2>
          <div className="mt-7 grid grid-cols-3 gap-2.5">
            {providers.map(({ name, icon: Icon, className }) => (
              <button
                key={name}
                type="button"
                className={`flex h-11 items-center justify-center gap-2 rounded-xl border bg-white text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-sm ${className}`}
              >
                <Icon size={16} />
                <span>{name}</span>
              </button>
            ))}
          </div>

          <div className="mt-6 flex items-center gap-3 text-xs text-[#7A899A]">
            <div className="h-px flex-1 bg-[#E4E8F0]" />
            <span>or continue with email</span>
            <div className="h-px flex-1 bg-[#E4E8F0]" />
          </div>

          <form
            className="mt-6 space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              setMessage("Authentication UI only. Connect the Django authentication API to continue.");
            }}
          >
            {isRegister && (
              <label className="block">
                <span className="mb-2 block text-sm font-medium text-[#34394B]">Full name</span>
                <input required autoComplete="name" placeholder="Your name" className="h-12 w-full rounded-[13px] border border-[#E4E8F0] bg-white px-4 text-sm outline-none transition placeholder:text-[#9AA6BB] focus:border-[#7188F9] focus:ring-4 focus:ring-[#7188F9]/10" />
              </label>
            )}

            <label className="block">
              <span className="mb-2 block text-sm font-medium text-[#34394B]">Email address</span>
              <input required type="email" autoComplete="email" placeholder="you@example.com" className="h-12 w-full rounded-[13px] border border-[#E4E8F0] bg-white px-4 text-sm outline-none transition placeholder:text-[#9AA6BB] focus:border-[#7188F9] focus:ring-4 focus:ring-[#7188F9]/10" />
            </label>

            <label className="block">
              <span className="mb-2 block text-sm font-medium text-[#34394B]">Password</span>
              <span className="relative block">
                <input
                  required
                  minLength={8}
                  type={showPassword ? "text" : "password"}
                  autoComplete={isRegister ? "new-password" : "current-password"}
                  placeholder={isRegister ? "At least 8 characters" : "Enter your password"}
                  className="h-12 w-full rounded-[13px] border border-[#E4E8F0] bg-white px-4 pr-12 text-sm outline-none transition placeholder:text-[#9AA6BB] focus:border-[#7188F9] focus:ring-4 focus:ring-[#7188F9]/10"
                />
                <button
                  type="button"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-[#71809A] hover:bg-[#F6F8FC]"
                >
                  {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                </button>
              </span>
            </label>

            {!isRegister && (
              <div className="flex items-center justify-between text-xs">
                <label className="flex items-center gap-2 text-[#71809A]">
                  <input type="checkbox" className="accent-[#7188F9]" />
                  Remember me
                </label>
                <a
                  href="#forgot-password"
                  onClick={(e) => {
                    e.preventDefault();
                    setMessage("Password recovery will be available after connecting the authentication API.");
                  }}
                  className="font-semibold text-[#7188F9]"
                >
                  Forgot password?
                </a>
              </div>
            )}

            {message && <p role="status" className="rounded-xl bg-[#EEF1FF] p-3 text-xs leading-5 text-[#5F75E8]">{message}</p>}

            <button type="submit" className="flex h-12 w-full items-center justify-center gap-2 rounded-[13px] bg-[#7188F9] text-sm font-semibold text-white transition hover:bg-[#5F75E8]">
              {isRegister ? "Create account" : "Sign in"}
              <ArrowRight size={17} />
            </button>
          </form>

          <p className="mt-7 text-center text-sm text-[#71809A]">
            {isRegister ? "Already have an account?" : "Don't have an account?"}{" "}
            <Link href={isRegister ? "/login" : "/register"} className="font-semibold text-[#7188F9] hover:text-[#5F75E8]">
              {isRegister ? "Sign in" : "Create account"}
            </Link>
          </p>

        </div>
    </main>
  );
}
