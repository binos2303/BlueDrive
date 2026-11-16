import type { Metadata } from "next";
import type { ReactNode } from "react";

import localFont from "next/font/local";
import "./globals.css";
import UploadManager from "@/components/drive/UploadManager";
import AccountProvider from "@/components/account/AccountProvider";
import ThemeProvider from "@/components/theme/ThemeProvider";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

const poppins = localFont({
  src: [
    { path: "./fonts/poppins/Poppins-Regular.ttf", weight: "400", style: "normal" },
    { path: "./fonts/poppins/Poppins-Medium.ttf", weight: "500", style: "normal" },
    { path: "./fonts/poppins/Poppins-SemiBold.ttf", weight: "600", style: "normal" },
    { path: "./fonts/poppins/Poppins-Bold.ttf", weight: "700", style: "normal" },
  ],
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
    <html lang="en" className={poppins.variable} suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} /></head>
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
