import type { Metadata } from "next";
import type { ReactNode } from "react";

import { Poppins } from "next/font/google";
import "./globals.css";

const poppins = Poppins({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-poppins",
});

export const metadata: Metadata = {
  title: "BlueDrive",
  description: "Secure cloud storage for your files",
};

export default function RootLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <html lang="en" className={poppins.variable}>
      <body className="min-h-screen bg-[#F3F5F9] font-sans text-[#121523] antialiased">
        {children}
      </body>
    </html>
  );
}