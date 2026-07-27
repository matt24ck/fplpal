import type { Metadata, Viewport } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { Archivo, IBM_Plex_Mono, Instrument_Sans } from "next/font/google";
import "./globals.css";
import { Providers } from "@/lib/providers";
import { Shell } from "@/components/Shell";
import { SITE_NAME, SITE_URL } from "@/lib/seo";

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
  metadataBase: new URL(SITE_URL),
  applicationName: SITE_NAME,
  title: {
    default: "FPL Pal — your pal who does the maths",
    template: `%s · ${SITE_NAME}`,
  },
  description:
    "FPL projections, ratings and optimal squads computed by a statistical engine — explained by Pal, an AI assistant that never invents a number.",
};

export const viewport: Viewport = {
  themeColor: "#240540",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // Default (non-dynamic) ClerkProvider: auth state resolves client-side, so
    // the ISR/static prerenders of public pages are untouched.
    <ClerkProvider>
      <html lang="en">
        <body
          className={`${archivo.variable} ${instrument.variable} ${plexMono.variable} antialiased`}
        >
          <Providers>
            <Shell>{children}</Shell>
          </Providers>
        </body>
      </html>
    </ClerkProvider>
  );
}
