import "./globals.css";

export const metadata = {
  title: "Inverter Load Manager",
  description: "Keep a home inverter at or under 800 watts.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
