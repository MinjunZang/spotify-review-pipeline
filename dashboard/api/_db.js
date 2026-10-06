// Shared read-only Postgres access. DATABASE_URL is a Vercel environment variable, never sent to the browser.
import { neon } from "@neondatabase/serverless";

export const sql = neon(process.env.DATABASE_URL);

export function send(res, data, status = 200) {
  res.setHeader("Cache-Control", "s-maxage=300, stale-while-revalidate=3600");
  res.status(status).json(data);
}

export function fail(res, err) {
  console.error(err);
  res.status(500).json({ error: "database query failed" });
}
