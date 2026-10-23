import type { Metadata } from "next";
import type { ReactNode } from "react";

import { Poppins } from "next/font/google";
import "./globals.css";
import UploadManager from "@/components/drive/UploadManager";
import AccountProvider from "@/components/account/AccountProvider";
import ThemeProvider from "@/components/theme/ThemeProvider";

const poppins = Poppins({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-poppins",
  display: "swap",
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
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="en" className={poppins.variable}>
      <body
        className={`${poppins.className} min-h-screen bg-background text-foreground antialiased`}
      >
        <ThemeProvider>
          <AccountProvider>
            <UploadManager>{children}</UploadManager>
          </AccountProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
