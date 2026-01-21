/** @type {import('next').NextConfig} */
const nextConfig = {
  // Cross-origin 개발 허용 (외부 IP 접속용)
  allowedDevOrigins: ["*"],

  // 백엔드 API 프록시 (CORS 우회용, 선택)
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/:path*",
      },
    ];
  },
};

export default nextConfig;
