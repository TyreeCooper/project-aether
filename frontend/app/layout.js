import "./globals.css";

export const metadata = {
  title: "AETHER — Autonomous Paper Firm",
  description: "AETHER vNext autonomous PAPER trading operator console",
  icons: {
    icon: "/vnext/favicon.png",
    shortcut: "/vnext/favicon.png",
    apple: "/vnext/aether-mark.png",
  },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
        <meta name="theme-color" content="#07111d" />
        <link rel="icon" href="/vnext/favicon.png" type="image/png" />
        <link rel="apple-touch-icon" href="/vnext/aether-mark.png" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="mobile-web-app-capable" content="yes" />
      </head>
      <body>{children}</body>
    </html>
  );
}
