export async function onRequest({ env }) {
  const now = Date.now();
  const cutoff = now - 72 * 60 * 60 * 1000; // 72 hours ago

  const query = `
    SELECT id, source, sourceName, title_en, title_zh, link, timestamp, category, description, tags
    FROM news
    WHERE timestamp > ?
    ORDER BY timestamp DESC
    LIMIT 500
  `;

  let items = [];
  try {
    const result = await env.DB.prepare(query).bind(cutoff).all();
    items = result.results || [];
  } catch (err) {
    console.error("D1 query error:", err);
    return new Response(JSON.stringify({ error: "Database error", items: [], total: 0 }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response(JSON.stringify({
    items,
    total: items.length,
    fetchedAt: now,
  }), {
    headers: { "Content-Type": "application/json" },
  });
}
