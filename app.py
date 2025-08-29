import os
import random
import string
import time
import threading
from flask import Flask, request, send_file, render_template
from flask import Flask, request, send_file, render_template, url_for
import os, random, string, time, threading
from werkzeug.utils import secure_filename

app = Flask(__name__)

# --- Config ---
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB
LINK_EXPIRY = 15 * 60  # 15 minutes in seconds

# Store mapping: { random_id: {"path":..., "time":...} }
file_links = {}

def generate_random_string(length=8):
    """Generate random ID for each file link"""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

@app.errorhandler(413)
def file_too_large(e):
    return "File is too large. Max limit is 100 MB.", 413

@app.route("/", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        if 'file' not in request.files:
            return render_template("index.html", link=None, error="No file selected")

        file = request.files['file']
        if file.filename == "":
            return render_template("index.html", link=None, error="No file selected")

        # Save uploaded file
        filename = file.filename
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)

        # Generate random link ID
        random_id = generate_random_string()
        file_links[random_id] = {
            "path": filepath,
            "time": time.time()
        }

        share_link = request.host_url + random_id
        # Render the same page but with the link
        return render_template("index.html", link=share_link, error=None)

    # GET request: just show the page without a link
    return render_template("index.html", link=None, error=None)



@app.route("/<random_id>")
def download(random_id):
    file_info = file_links.get(random_id)
    if not file_info:
        return "Invalid or expired link", 404

    # Expiry check
    if time.time() - file_info["time"] > LINK_EXPIRY:
        try:
            os.remove(file_info["path"])
        except FileNotFoundError:
            pass
        file_links.pop(random_id, None)
        return "Link expired", 410

    filename = os.path.basename(file_info["path"])
    dl_url = url_for("direct_download", random_id=random_id)
    del_url = url_for("delete_file", random_id=random_id)

    return render_template("download.html", filename=filename, download_url=dl_url, delete_url=del_url)


@app.route("/download/<random_id>")
def direct_download(random_id):
    """Direct file sending (used by the styled page's button)"""
    file_info = file_links.get(random_id)
    if not file_info:
        return "Invalid or expired link", 404
    return send_file(file_info["path"], as_attachment=True)


@app.route("/delete/<random_id>", methods=["POST"])
def delete_file(random_id):
    """Delete file manually before expiry"""
    file_info = file_links.get(random_id)
    if not file_info:
        return "Invalid or expired link", 404

    try:
        os.remove(file_info["path"])
    except FileNotFoundError:
        pass

    file_links.pop(random_id, None)

    return render_template("deleted.html")

# --- Background cleaner thread ---
def cleanup_expired_files():
    """Periodically remove files older than LINK_EXPIRY"""
    while True:
        now = time.time()
        expired_keys = []
        for key, info in list(file_links.items()):
            if now - info["time"] > LINK_EXPIRY:
                # Delete the file
                try:
                    os.remove(info["path"])
                except FileNotFoundError:
                    pass
                expired_keys.append(key)

        # Remove expired entries
        for key in expired_keys:
            del file_links[key]

        time.sleep(60)  # Check every 60 seconds

# Start background thread for cleaning expired files
threading.Thread(target=cleanup_expired_files, daemon=True).start()

if __name__ == "__main__":
    app.run(debug=True)