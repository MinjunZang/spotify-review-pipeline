// GET /api/memo -> AI-generated recommendation memo, its code check, and every claim it can cite
import { sql, send, fail } from "./_db.js";

export default async function handler(req, res) {
  try {
    const [[memo], claims] = await Promise.all([
      sql`SELECT * FROM memo WHERE id = 1`,
      sql`SELECT * FROM claims ORDER BY claim_id`,
    ]);
    const ids = memo?.cited_review_ids || [];
    const cited = ids.length
      ? await sql`SELECT review_id, issue_id, topic, intent, severity, evidence_quote FROM reviews WHERE review_id = ANY(${ids})`
      : [];
    send(res, { memo, claims, cited_reviews: cited });
  } catch (e) { fail(res, e); }
}
