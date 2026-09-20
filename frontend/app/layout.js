import "./globals.css";

export const metadata = {
  title: "Project Aether",
  description: "BTC/USD automated trading dashboard",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
