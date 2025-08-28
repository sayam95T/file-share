export const config = {
  api: {
    bodyParser: false, // Let us stream the file
  },
};

export default async function handler(req, res) {
  if (req.method !== "POST") {
    res.status(405).json({ error: "Method not allowed" });
    return;
  }

  try {
    const response = await fetch("https://file.io/?expires=1d", {
      method: "POST",
      headers: {
        "Content-Type": req.headers["content-type"] || "multipart/form-data",
      },
      body: req, // Stream body directly to file.io
    });

    const data = await response.json();
    res.setHeader("Access-Control-Allow-Origin", "*"); // CORS
    res.status(response.status).json(data);
  } catch (err) {
    res.status(500).json({ error: "Upload failed", details: err.toString() });
  }
}
