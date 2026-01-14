import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AX Agent - AI 연구 데이터 어시스턴트",
  description: "특허, 연구과제, 장비 정보를 검색하고 분석하는 AI 어시스턴트",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
