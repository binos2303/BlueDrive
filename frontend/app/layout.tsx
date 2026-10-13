import type { Metadata } from "next";
import type { ReactNode } from "react";

import { Poppins } from "next/font/google";
import "./globals.css";
import UploadManager from "@/components/drive/UploadManager";
import AccountProvider from "@/components/account/AccountProvider";

const poppins = Poppins({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-poppins",
});

export const metadata: Metadata = {
  title: "BlueDrive",
  description: "Secure cloud storage for your files",
  icons: {
    icon: "/icon.svg",
    shortcut: "/icon.svg",
    apple: "/icon.svg",
  },
};

export default function RootLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <html lang="en" className={poppins.variable}>
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        <AccountProvider>
          <UploadManager>{children}</UploadManager>
        </AccountProvider>
      </body>
    </html>
  );
}