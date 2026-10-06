// GET /api/overview -> coverage, intents, product-area aggregates, trend windows, monthly series, run evidence
import { sql, send, fail } from "./_db.js";

export default async function handler(req, res) {
  try {
    const [meta, areas, trend, monthly] = await Promise.all([
      sql`SELECT key, value FROM meta`,
      sql`SELECT * FROM areas ORDER BY severity_sum DESC`,
      sql`SELECT * FROM trend ORDER BY area`,
      sql`SELECT month, area, complaints, completed FROM monthly ORDER BY month, area`,
    ]);
    send(res, { meta: Object.fromEntries(meta.map((m) => [m.key, m.value])), areas, trend, monthly });
  } catch (e) { fail(res, e); }
}
