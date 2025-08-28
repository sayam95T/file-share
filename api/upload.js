export const config = {
  runtime: "edge", // run on Edge
};

export default async function handler(req) {
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "Method not allowed" }), {
      status: 405,
      headers: { "Content-Type": "application/json" },
    });
  }

  try {
    // Forward the upload stream to file.io
    const response = await fetch("https://file.io/?expires=1d", {
      method: "POST",
      headers: {
        "Content-Type": req.headers.get("content-type") || "multipart/form-data",
      },
      body: req.body, // req.body is already a stream in Edge functions
    });

    const data = await response.json();

    return new Response(JSON.stringify(data), {
      status: response.status,
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Content-Type": "application/json",
      },
    });
  } catch (err) {
    return new Response(
      JSON.stringify({ error: "Upload failed", details: err.message }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }
    );
  }
}

