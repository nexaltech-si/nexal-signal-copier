import { SignUp } from "@clerk/nextjs";

export default function Page() {
  return (
    <div className="flex min-h-screen items-center justify-center premium-bg">
      <div className="glow-effect" />
      <div className="relative z-10">
        <SignUp appearance={{
          elements: {
            formButtonPrimary: 'bg-primary hover:bg-primary/90 text-sm normal-case',
            card: 'bg-white/80 backdrop-blur-xl border border-white/20 shadow-2xl rounded-2xl',
          }
        }} />
      </div>
    </div>
  );
}
