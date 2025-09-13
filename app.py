import os
import random
import string
import time
import threading
import logging
from flask import Flask, request, render_template, url_for
from werkzeug.utils import secure_filename
import boto3

# --- App setup ---
app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

# --- Cloudflare R2 Config ---
R2_ACCOUNT_ID = "your_account_id_here"
R2_ACCESS_KEY = "your_access_key_here"
R2_SECRET_KEY = "your_secret_key_here"
R2_BUCKET = "droppr-videos"  # your bucket name

# R2 client
session = boto3.session.Session()
r2 = session.client(
    service_name="s3",
    endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
)

app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB
LINK_EXPIRY = 15 * 60  # 15 minutes in seconds

# Store mapping: { random_id: {"url":..., "time":...} }
file_links = {}


def generate_random_string(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


@app.errorhandler(413)
def file_too_large(e):
    return "File is too large. Max limit is 100 MB.", 413


# ------------------- Normal File Sharing -------------------

@app.route("/", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        if "file" not in request.files:
            return render_template("index.html", link=None, error="No file selected")

        file = request.files["file"]
        if file.filename == "":
            return render_template("index.html", link=None, error="No file selected")

        filename = secure_filename(file.filename)

        # Upload to R2
        r2.upload_fileobj(file, R2_BUCKET, filename)

        # Public R2 URL
        file_url = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com/{R2_BUCKET}/{filename}"

        random_id = generate_random_string()
        file_links[random_id] = {"url": file_url, "time": time.time()}

        share_link = request.host_url + random_id
        return render_template("index.html", link=share_link, error=None)

    return render_template("index.html", link=None, error=None)


@app.route("/<random_id>")
def download(random_id):
    file_info = file_links.get(random_id)
    if not file_info:
        return "Invalid or expired link", 404

    if time.time() - file_info["time"] > LINK_EXPIRY:
        file_links.pop(random_id, None)
        return "Link expired", 410

    filename = os.path.basename(file_info["url"])
    dl_url = file_info["url"]
    del_url = url_for("delete_file", random_id=random_id)

    return render_template("download.html",
                           filename=filename,
                           download_url=dl_url,
                           delete_url=del_url,
                           random_id=random_id)


@app.route("/delete/<random_id>", methods=["POST"])
def delete_file(random_id):
    file_info = file_links.get(random_id)
    if not file_info:
        return "Invalid or expired link", 404

    filename = os.path.basename(file_info["url"])

    try:
        r2.delete_object(Bucket=R2_BUCKET, Key=filename)
    except Exception as e:
        app.logger.error(f"Delete error: {e}")

    file_links.pop(random_id, None)
    return render_template("deleted.html")


# ------------------- Video Sharing -------------------

@app.route("/video.com", methods=["GET", "POST"])
def video_upload():
    if request.method == "POST":
        if "file" not in request.files:
            return render_template("video_upload.html", link=None, error="No file selected")

        file = request.files["file"]
        if file.filename == "":
            return render_template("video_upload.html", link=None, error="No file selected")

        filename = secure_filename(file.filename)

        # Upload to R2
        r2.upload_fileobj(file, R2_BUCKET, filename)

        file_url = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com/{R2_BUCKET}/{filename}"

        random_id = generate_random_string()
        file_links[random_id] = {"url": file_url, "time": time.time()}

        share_link = request.host_url + "v/" + random_id
        return render_template("video_upload.html", link=share_link, error=None)

    return render_template("video_upload.html", link=None, error=None)


@app.route("/v/<random_id>")
def video_view(random_id):
    file_info = file_links.get(random_id)
    if not file_info:
        return "Invalid or expired link", 404

    if time.time() - file_info["time"] > LINK_EXPIRY:
        file_links.pop(random_id, None)
        return "Link expired", 410

    file_url = file_info["url"]
    filename = os.path.basename(file_url)
    del_url = url_for("delete_file", random_id=random_id)

    return render_template("video_view.html",
                           filename=filename,
                           file_url=file_url,
                           download_url=file_url,
                           delete_url=del_url,
                           random_id=random_id)


# ------------------- Cleaner -------------------

def cleanup_expired_files():
    while True:
        now = time.time()
        expired_keys = [key for key, info in list(file_links.items())
                        if now - info["time"] > LINK_EXPIRY]

        for key in expired_keys:
            file_links.pop(key, None)

        time.sleep(60)


threading.Thread(target=cleanup_expired_files, daemon=True).start()

if __name__ == "__main__":
    app.run(debug=True)
