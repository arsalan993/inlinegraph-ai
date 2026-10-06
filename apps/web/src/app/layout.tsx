import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "InlineGraph AI — Explore answers one passage at a time",
  description: "Branch from a passage, explore an idea, and choose what belongs in your answer.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
