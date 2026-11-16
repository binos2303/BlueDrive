import AuthForm from "@/components/layout/AuthForm";
export default async function RegisterPage({ searchParams }: { searchParams: Promise<{ next?: string | string[] }> }) {
  const { next } = await searchParams;
  return <AuthForm mode="register" nextPath={typeof next === "string" ? next : undefined} />;
}
