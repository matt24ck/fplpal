import type { Metadata, Viewport } from "next";
import { Archivo, IBM_Plex_Mono, Instrument_Sans } from "next/font/google";
import "./globals.css";
import { Providers } from "@/lib/providers";
import { Shell } from "@/components/Shell";

const archivo = Archivo({
  subsets: ["latin"],
  variable: "--font-archivo",
  axes: ["wdth"],
});
const instrument = Instrument_Sans({
  subsets: ["latin"],
  variable: "--font-instrument",
});
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex",
});

export const metadata: Metadata = {
  title: "The Board — FPL AI Assistant",
  description:
    "FPL projections, ratings and squad optimization from a statistical engine, explained through grounded AI chat.",
};

export const viewport: Viewport = {
  themeColor: "#f6f8f6",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body
        className={`${archivo.variable} ${instrument.variable} ${plexMono.variable} antialiased`}
      >
        <Providers>
          <Shell>{children}</Shell>
        </Providers>
      </body>
    </html>
  );
}
