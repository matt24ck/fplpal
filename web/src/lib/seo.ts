import type { Metadata } from "next";

/** Canonical production origin. Override with NEXT_PUBLIC_SITE_URL if the
 * primary host ever changes (www vs apex, preview deploys). */
export const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL ?? "https://fplpal.com";

export const SITE_NAME = "FPL Pal";

const TWITTER_HANDLE = "@TheBoardFPL";

/** Metadata for one route: unique title/description plus the canonical and
 * OG/Twitter tags that make the URL preview as itself rather than as the
 * homepage. `absoluteTitle` opts out of the layout's "%s · FPL Pal" template
 * (the homepage carries the brand in the title already). */
export function pageMetadata({
  title,
  description,
  path,
  absoluteTitle = false,
}: {
  title: string;
  description: string;
  path: string;
  absoluteTitle?: boolean;
}): Metadata {
  return {
    title: absoluteTitle ? { absolute: title } : title,
    description,
    alternates: { canonical: path },
    openGraph: {
      title,
      description,
      url: path,
      siteName: SITE_NAME,
      type: "website",
    },
    twitter: {
      card: "summary",
      site: TWITTER_HANDLE,
      title,
      description,
    },
  };
}
