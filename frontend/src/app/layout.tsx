import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { Nav } from "@/components/Nav";

export const metadata: Metadata = {
  title: "LostLink AI",
  description: "AI-assisted lost & found: report, match, verify and recover.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <Nav />
          <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
          <footer className="mx-auto max-w-6xl px-4 pb-10 text-xs text-slate-500">
            LostLink AI suggests potential matches. It never guarantees a match or establishes ownership; people
            verify ownership before any connection is made.
          </footer>
        </AuthProvider>
      </body>
    </html>
  );
}
