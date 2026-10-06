// GET /api/issue?id=playback.crash_freeze&offset=0 -> issue row, curated examples, claims, paged member reviews
import { sql, send, fail } from "./_db.js";

export default async function handler(req, res) {
  const id = String(req.query.id || "");
  const offset = Math.max(0, parseInt(req.query.offset || "0", 10) || 0);
  try {
    const [issue] = await sql`SELECT * FROM issues WHERE issue_id = ${id}`;
    if (!issue) return send(res, { error: "unknown issue" }, 404);
    const [examples, claims, members] = await Promise.all([
      sql`SELECT * FROM issue_examples WHERE issue_id = ${id}`,
      sql`SELECT * FROM claims WHERE subject = ${id} ORDER BY claim_id`,
      sql`SELECT review_id, intent, severity, sentiment, evidence_quote, review_timestamp, review_rating, cache_source_id
          FROM reviews WHERE issue_id = ${id} ORDER BY severity DESC, review_id LIMIT 25 OFFSET ${offset}`,
    ]);
    send(res, { issue, examples, claims, members, offset });
  } catch (e) { fail(res, e); }
}
