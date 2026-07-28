"use client";

import { SignInButton, UserButton, useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useState } from "react";
import { countdown } from "@/lib/format";
import { useMeta } from "@/lib/hooks";
import { useApp } from "@/lib/store";
import { StatusBar } from "./StatusBar";
import { ChatRail } from "./chat/ChatRail";

const NAV = [
  { href: "/", label: "My Team", short: "Team", icon: PitchIcon },
  { href: "/builder", label: "Builder", short: "Builder", icon: BuilderIcon },
  { href: "/planner", label: "Planner", short: "Plan", icon: PlanIcon },
  { href: "/players", label: "Players", short: "Players", icon: PlayersIcon },
  { href: "/fixtures", label: "Fixtures", short: "Fixtures", icon: FixturesIcon },
  // appended after the mobile tab slice's indices (0-4) — don't reorder above
  { href: "/accuracy", label: "Accuracy", short: "Accuracy", icon: AccuracyIcon },
  { href: "/about", label: "About", short: "About", icon: AboutIcon },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { chatOpen, setChatOpen } = useApp();
  const { isLoaded, isSignedIn } = useAuth();
  const onChatPage = pathname === "/chat";
  /* The rail mounts client-side only. During streaming SSR the page chunk
   * arrives late, so Shell siblings render first — if the rail subscribed to
   * ["explorer"] then, the page's HydrationBoundary would find the query
   * already in the cache and defer hydration to a client effect, stripping
   * the data out of the prerendered HTML (see lib/engine-server.ts). */
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  return (
    <div className="flex min-h-dvh flex-col">
      {/* masthead */}
      <header className="masthead text-chalk sticky top-0 z-50">
        <div className="flex h-14 items-center gap-5 px-4 sm:px-6">
          <Link href="/" className="flex items-center gap-2" aria-label="FPL Pal — home">
            <PalMark className="h-5 w-5" />
            <span className="font-hero text-lg leading-none">
              FPL <span className="text-brand-gradient">PAL</span>
            </span>
          </Link>

          <nav aria-label="Main" className="hidden h-full items-stretch gap-1 lg:flex">
            {NAV.map(({ href, label }) => {
              const active = pathname === href;
              return (
                <Link
                  key={href}
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={`font-chip flex items-center border-b-2 px-3 text-[13px] font-bold tracking-wide ${
                    active
                      ? "border-neon text-chalk"
                      : "text-chalk/65 hover:text-chalk border-transparent"
                  }`}
                >
                  {label}
                </Link>
              );
            })}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <DeadlineChip />
            {/* About lives in the tab bar's blind spot — surface it up here on mobile */}
            <Link
              href="/about"
              aria-current={pathname === "/about" ? "page" : undefined}
              aria-label="About FPL Pal"
              className={`flex h-8 w-8 items-center justify-center rounded-full lg:hidden ${
                pathname === "/about"
                  ? "bg-chalk/15 text-chalk"
                  : "text-chalk/70 hover:text-chalk"
              }`}
            >
              <AboutIcon />
            </Link>
            {!onChatPage && !chatOpen && (
              <button
                onClick={() => setChatOpen(true)}
                className="btn-primary hidden items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm lg:flex"
              >
                <SparkIcon className="h-3.5 w-3.5" />
                Ask Pal
              </button>
            )}
            {isLoaded &&
              (isSignedIn ? (
                <UserButton />
              ) : (
                <SignInButton mode="modal">
                  <button className="border-chalk/35 text-chalk hover:border-chalk rounded-full border px-3.5 py-1.5 text-sm font-medium">
                    Sign in
                  </button>
                </SignInButton>
              ))}
          </div>
        </div>
      </header>

      <div className="flex flex-1">
        {/* main canvas */}
        <main className="min-w-0 flex-1 pb-24 lg:pb-10">{children}</main>

        {/* Pal rail — desktop */}
        {mounted && !onChatPage && chatOpen && (
          <aside className="border-line sticky top-14 hidden h-[calc(100dvh-3.5rem)] w-[380px] shrink-0 border-l xl:w-[420px] lg:flex lg:flex-col">
            <ChatRail onCollapse={() => setChatOpen(false)} />
          </aside>
        )}
      </div>

      <StatusBar />

      {/* mobile bottom tabs — Pal at center */}
      <nav
        aria-label="Main"
        className="border-line bg-chalk fixed inset-x-0 bottom-0 z-40 flex border-t pb-[env(safe-area-inset-bottom)] shadow-[0_-2px_10px_rgba(25,18,39,0.06)] lg:hidden"
      >
        {[NAV[0], NAV[1], null, NAV[3], NAV[4]].map((item) =>
          item === null ? (
            <Link
              key="chat"
              href="/chat"
              aria-current={onChatPage ? "page" : undefined}
              aria-label="Ask Pal"
              className="flex flex-1 flex-col items-center gap-0.5 py-1.5"
            >
              <span
                className={`flex h-10 w-10 -translate-y-2.5 items-center justify-center rounded-full shadow-lg ${
                  onChatPage ? "bg-deep text-neon" : "btn-primary"
                }`}
              >
                <SparkIcon className="h-4.5 w-4.5" />
              </span>
              <span
                className={`-mt-2 text-[10px] font-semibold ${
                  onChatPage ? "text-royal" : "text-slate"
                }`}
              >
                Pal
              </span>
            </Link>
          ) : (
            <Link
              key={item.href}
              href={item.href}
              aria-current={pathname === item.href ? "page" : undefined}
              className={`flex min-h-11 flex-1 flex-col items-center justify-center gap-0.5 py-1.5 text-[10px] font-medium ${
                pathname === item.href ? "text-royal" : "text-slate"
              }`}
            >
              <item.icon />
              <span>{item.short}</span>
            </Link>
          ),
        )}
      </nav>

      {/* collapsed Pal — desktop */}
      {!onChatPage && !chatOpen && (
        <button
          onClick={() => setChatOpen(true)}
          className="btn-primary fixed right-5 bottom-12 z-40 hidden items-center gap-2 rounded-full px-4 py-2.5 text-sm shadow-lg lg:flex"
          aria-label="Open Pal"
        >
          <SparkIcon className="h-4 w-4" />
          Ask Pal
        </button>
      )}
    </div>
  );
}

/** GW deadline, always in view — the one clock every manager plays against.
 * Split so useMeta only runs after mount: it renders null pre-mount anyway,
 * and subscribing during SSR would block ["meta"] hydration (see Shell). */
function DeadlineChip() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const t = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(t);
  }, []);

  if (!now) return null;
  return <DeadlineChipInner now={now} />;
}

function DeadlineChipInner({ now }: { now: Date }) {
  const { data } = useMeta();
  const dl = data?.next_deadline;
  if (!dl) return null;
  const left = countdown(dl.deadline_time, now);
  const urgent = new Date(dl.deadline_time).getTime() - now.getTime() < 86_400_000;

  return (
    <span className="hidden items-center gap-1.5 font-mono text-xs sm:flex" title="Next deadline">
      <span
        className={`pal-dot h-1.5 w-1.5 rounded-full ${urgent ? "bg-hot" : "bg-neon"}`}
        aria-hidden
      />
      <span className="text-chalk/75">
        GW{dl.gw} <span className="text-chalk font-semibold">{left}</span>
      </span>
    </span>
  );
}

export function PalMark({ className }: { className?: string }) {
  const id = useId().replace(/[^a-zA-Z0-9-]/g, "");
  return (
    <svg viewBox="0 0 20 20" className={className} aria-hidden>
      <defs>
        <linearGradient id={`palmark-${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#00ef85" />
          <stop offset="100%" stopColor="#04d9f5" />
        </linearGradient>
      </defs>
      <rect width="20" height="20" rx="5" fill={`url(#palmark-${id})`} />
      <path
        d="M10 3.5 11.6 8.4 16.5 10 11.6 11.6 10 16.5 8.4 11.6 3.5 10 8.4 8.4 Z"
        fill="#17052b"
      />
    </svg>
  );
}

export function SparkIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" className={className} aria-hidden>
      <path d="M10 2.5 11.9 8.1 17.5 10 11.9 11.9 10 17.5 8.1 11.9 2.5 10 8.1 8.1 Z" />
    </svg>
  );
}

function PitchIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
      <rect x="3" y="2" width="14" height="16" rx="1" stroke="currentColor" strokeWidth="1.5" />
      <path d="M3 10h14M7 2v2.5a3 3 0 0 0 6 0V2M7 18v-2.5a3 3 0 0 1 6 0V18" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}
function BuilderIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
      <path d="M10 4v12M4 10h12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}
function PlanIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
      <path d="M3 15V5m4.5 10V8M12 15v-5m4.5 5V4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
function PlayersIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
      <circle cx="7" cy="7" r="3" stroke="currentColor" strokeWidth="1.5" />
      <path d="M2.5 17a4.5 4.5 0 0 1 9 0" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="14.5" cy="8" r="2.2" stroke="currentColor" strokeWidth="1.3" />
      <path d="M12.8 12.6a3.6 3.6 0 0 1 4.7 3.4" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  );
}
function FixturesIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
      <rect x="3" y="4" width="14" height="13" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
      <path d="M3 8.5h14M7.5 4v13M12.5 4v13" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}
function AccuracyIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
      <circle cx="10" cy="10" r="7.5" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="10" cy="10" r="4" stroke="currentColor" strokeWidth="1.3" />
      <circle cx="10" cy="10" r="1.2" fill="currentColor" />
    </svg>
  );
}
function AboutIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
      <circle cx="10" cy="10" r="7.5" stroke="currentColor" strokeWidth="1.5" />
      <path d="M10 9v4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="10" cy="6.2" r="1" fill="currentColor" />
    </svg>
  );
}
