import type { Metadata } from "next";
import { SignIn } from "@clerk/nextjs";

export const metadata: Metadata = {
  title: "Sign in",
  robots: { index: false },
};

export default function SignInPage() {
  return (
    <div className="flex justify-center px-4 py-12 sm:py-16">
      <SignIn />
    </div>
  );
}
