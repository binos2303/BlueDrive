import AuthForm from "@/components/layout/AuthForm";
export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string | string[] }> }) {
  const { next } = await searchParams;
  return <AuthForm mode="login" nextPath={typeof next === "string" ? next : undefined} />;
}
