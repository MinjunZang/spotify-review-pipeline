// GET /api/review?id=<review_id> -> one record traced to its issue, rank and the claims about that issue
import { sql, send, fail } from "./_db.js";

export default async function handler(req, res) {
  const id = String(req.query.id || "");
  try {
    const [review] = await sql`SELECT * FROM reviews WHERE review_id = ${id}`;
    if (!review) return send(res, { error: "unknown review_id" }, 404);
    const [issue] = review.issue_id ? await sql`SELECT * FROM issues WHERE issue_id = ${review.issue_id}` : [];
    const claims = review.issue_id ? await sql`SELECT * FROM claims WHERE subject = ${review.issue_id}` : [];
    send(res, { review, issue: issue || null, claims });
  } catch (e) { fail(res, e); }
}
