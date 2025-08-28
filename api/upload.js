export const config = {
  runtime: "edge",  // 👈 use edge runtime
};

export default async function handler(req) {
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "Method not allowed" }), { status: 405 });
  }

  try {
    const response = await fetch("https://file.io/?expires=1d", {
      method: "POST",
      headers: { "Content-Type": req.headers.get("content-type") || "multipart/form-data" },
      body: req.body, // forward stream directly
    });

    const data = await response.json();
    return new Response(JSON.stringify(data), {
      status: response.status,
      headers: { "Access-Control-Allow-Origin": "*" },
    });
  } catch (err) {
    return new Response(JSON.stringify({ error: "Upload failed", details: err.toString() }), { status: 500 });
  }
}

