import type { Metadata } from "next";
import { SignUp } from "@clerk/nextjs";

export const metadata: Metadata = {
  title: "Create account",
  robots: { index: false },
};

export default function SignUpPage() {
  return (
    <div className="flex justify-center px-4 py-12 sm:py-16">
      <SignUp />
    </div>
  );
}
