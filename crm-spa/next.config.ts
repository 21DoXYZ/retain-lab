import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // SPA раздаётся с КОРНЯ https://cas.21do.xyz — она единственный интерфейс,
  // точка входа /login. HTML-борд больше не отдаём наружу: player_board.py
  // остался headless-API (/api/v1/*), его страницы дублировали бы роуты SPA.
  // За Caddy: доверяем ему TLS-терминацию, наружу отдаём https-ссылки.
  output: "standalone",
  // Dev only: allow the dev client (HMR / hydration assets) when the app is
  // opened via 127.0.0.1 as well as localhost. Next 16 blocks cross-origin dev
  // resources by default; without this, hydration silently fails on 127.0.0.1
  // (login form falls back to a native submit). No effect on production builds.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
};

export default nextConfig;
