"use client";

export function PageShell({
  title,
  right,
  children,
}: {
  title: string;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6">
      <div className="mb-5 flex items-baseline justify-between">
        <h1 className="font-hero text-2xl tracking-tight">{title}</h1>
        {right}
      </div>
      {children}
    </div>
  );
}

export function Segmented({
  value,
  onChange,
  options,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  label: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="border-line bg-paper-2 flex rounded-full border p-0.5"
    >
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          aria-pressed={value === o.value}
          className={`rounded-full px-3 py-1 text-xs font-semibold ${
            value === o.value ? "bg-deep text-chalk shadow-sm" : "text-slate hover:text-ink"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
