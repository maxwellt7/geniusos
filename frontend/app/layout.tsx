import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { ClerkProvider, UserButton } from "@clerk/nextjs";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Limitless Chat",
  description: "Conversational search over your Limitless lifelogs",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // clerkJSUrl forces the script-tag hotload of clerk-js. @clerk/nextjs's
  // default entry-chunk loader fails on the Next 16 Turbopack production build
  // (failed_to_load_clerk_js -> blank screen). It's a valid runtime option but
  // not in NextClerkProviderProps' types, so pass it via a cast.
  const clerkProps = {
    afterSignOutUrl: "/",
    clerkJSUrl:
      "https://clerk.maxmayes.io/npm/@clerk/clerk-js@6/dist/clerk.browser.js",
  } as unknown as React.ComponentProps<typeof ClerkProvider>;
  return (
    <ClerkProvider {...clerkProps}>
      <html lang="en" className="dark">
        <body
          className={`${geistSans.variable} ${geistMono.variable} antialiased bg-zinc-950 text-zinc-100`}
        >
          <div className="fixed right-4 top-4 z-50">
            <UserButton />
          </div>
          {children}
        </body>
      </html>
    </ClerkProvider>
  );
}
