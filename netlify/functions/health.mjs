export async function handler(event) {
  if (event.httpMethod !== "GET") {
    return {
      statusCode: 405,
      headers: { "content-type": "application/json; charset=utf-8", allow: "GET" },
      body: JSON.stringify({ error: "Method not allowed." }),
    };
  }
  return {
    statusCode: 200,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
    body: JSON.stringify({ status: "ok" }),
  };
}

