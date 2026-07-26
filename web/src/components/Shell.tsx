"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useApp } from "@/lib/store";
import { StatusBar } from "./StatusBar";
import { ChatRail } from "./chat/ChatRail";

const NAV = [
  { href: "/", label: "My Team", short: "Team", icon: PitchIcon },
  { href: "/builder", label: "Squad Builder", short: "Draft", icon: BuilderIcon },
  { href: "/planner", label: "Planner", short: "Plan", icon: PlanIcon },
  { href: "/players", label: "Players", short: "Players", icon: PlayersIcon },
  { href: "/fixtures", label: "Fixtures", short: "Fixtures", icon: FixturesIcon },
  { href: "/about", label: "About", short: "About", icon: AboutIcon },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { chatOpen, setChatOpen } = useApp();
  const onChatPage = pathname === "/chat";

  return (
    <div className="flex min-h-dvh flex-col">
      <div className="flex flex-1">
        {/* left nav rail — desktop */}
        <nav
          aria-label="Main"
          className="border-line bg-paper sticky top-0 hidden h-dvh w-16 shrink-0 flex-col items-center gap-1 border-r pt-3 lg:flex"
        >
          <Link href="/" className="mb-3 block" aria-label="The Board — home">
            <span className="font-hero text-pitch-deep text-lg leading-none">TB</span>
          </Link>
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={`flex w-14 flex-col items-center gap-0.5 rounded-md px-1 py-2 text-[10px] font-medium ${
                  active
                    ? "bg-paper-2 text-pitch-deep"
                    : "text-slate hover:text-ink"
                }`}
              >
                <Icon />
                <span>{label.split(" ").pop()}</span>
              </Link>
            );
          })}
        </nav>

        {/* main canvas */}
        <main className="min-w-0 flex-1 pb-24 lg:pb-10">{children}</main>

        {/* chat rail — desktop */}
        {!onChatPage &&
          (chatOpen ? (
            <aside className="border-line sticky top-0 hidden h-dvh w-[380px] shrink-0 border-l xl:w-[420px] lg:flex lg:flex-col">
              <ChatRail onCollapse={() => setChatOpen(false)} />
            </aside>
          ) : (
            <button
              onClick={() => setChatOpen(true)}
              className="bg-pitch-deep text-chalk fixed right-5 bottom-12 z-40 hidden h-12 w-12 items-center justify-center rounded-full shadow-lg lg:flex"
              aria-label="Open assistant"
            >
              <ChatIcon />
            </button>
          ))}
      </div>

      <StatusBar />

      {/* mobile bottom tabs — chat at center */}
      <nav
        aria-label="Main"
        className="border-line bg-paper fixed inset-x-0 bottom-0 z-40 flex border-t pb-[env(safe-area-inset-bottom)] lg:hidden"
      >
        {[NAV[0], NAV[2], null, NAV[3], NAV[4]].map((item, i) =>
          item === null ? (
            <Link
              key="chat"
              href="/chat"
              aria-current={onChatPage ? "page" : undefined}
              className="flex flex-1 flex-col items-center py-2"
            >
              <span
                className={`flex h-9 w-9 items-center justify-center rounded-full ${
                  onChatPage ? "bg-pitch-deep text-chalk" : "bg-paper-2 text-pitch-deep"
                }`}
              >
                <ChatIcon />
              </span>
            </Link>
          ) : (
            <Link
              key={item.href}
              href={item.href}
              aria-current={pathname === item.href ? "page" : undefined}
              className={`flex min-h-11 flex-1 flex-col items-center justify-center gap-0.5 py-1.5 text-[10px] font-medium ${
                pathname === item.href ? "text-pitch-deep" : "text-slate"
              }`}
            >
              <item.icon />
              <span>{item.short}</span>
            </Link>
          ),
        )}
      </nav>
    </div>
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
function AboutIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
      <circle cx="10" cy="10" r="7.5" stroke="currentColor" strokeWidth="1.5" />
      <path d="M10 9v4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="10" cy="6.2" r="1" fill="currentColor" />
    </svg>
  );
}

function ChatIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
      <path
        d="M10 3c4.4 0 7.5 2.7 7.5 6.2 0 3.6-3.1 6.3-7.5 6.3-.8 0-1.6-.1-2.3-.3L4 17l.8-3.1c-1.4-1.1-2.3-2.7-2.3-4.7C2.5 5.7 5.6 3 10 3Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}
