import type { Metadata } from "next";
import "./globals.css";
import AuthGate from "@/components/AuthGate";
import Shell from "@/components/Shell";
import { LiveProvider } from "@/lib/live";

export const metadata: Metadata = {
  title: "MarketPilot",
  description: "Personal market intelligence and paper-trading platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthGate>
          <LiveProvider>
            <Shell>{children}</Shell>
          </LiveProvider>
        </AuthGate>
      </body>
    </html>
  );
}
