import os
import random
import string
import time
import threading
import logging
from flask import Flask, request, render_template, url_for
from werkzeug.utils import secure_filename
import boto3
from botocore.client import Config

# --- App setup ---
app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

# --- Cloudflare R2 Config ---
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY")
R2_BUCKET = os.getenv("R2_BUCKET")

# R2 client with SigV4
r2 = boto3.client(
    's3',
    region_name='auto',  # R2 default
    endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
    config=Config(signature_version='s3v4')
)

app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB
LINK_EXPIRY = 1440 * 60  # 24  hours in seconds

# Store mapping: { random_id: {"filename":..., "time":...} }
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
        if "file" not in request.files or request.files["file"].filename == "":
            return render_template("index.html", link=None, error="No file selected")

        file = request.files["file"]
        filename = secure_filename(file.filename)

        # Upload to R2
        r2.upload_fileobj(file, R2_BUCKET, filename)

        random_id = generate_random_string()
        file_links[random_id] = {"filename": filename, "time": time.time()}

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

    filename = file_info["filename"]
    del_url = url_for("delete_file", random_id=random_id)

    try:
        signed_url = r2.generate_presigned_url(
            'get_object',
            Params={'Bucket': R2_BUCKET, 'Key': filename},
            ExpiresIn=LINK_EXPIRY
        )
        return render_template(
            "download.html",
            filename=filename,
            download_url=signed_url,
            delete_url=del_url,
            random_id=random_id
        )
    except Exception as e:
        app.logger.error(f"Download error: {e}")
        return "Error generating download link", 500

@app.route("/delete/<random_id>", methods=["POST"])
def delete_file(random_id):
    file_info = file_links.get(random_id)
    if not file_info:
        return "Invalid or expired link", 404

    filename = file_info["filename"]

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
        if "file" not in request.files or request.files["file"].filename == "":
            return render_template("video_upload.html", link=None, error="No file selected")

        file = request.files["file"]
        filename = secure_filename(file.filename)

        # Upload to R2
        r2.upload_fileobj(file, R2_BUCKET, filename)

        random_id = generate_random_string()
        file_links[random_id] = {"filename": filename, "time": time.time()}

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

    filename = file_info["filename"]
    del_url = url_for("delete_file", random_id=random_id)

    try:
        signed_url = r2.generate_presigned_url(
            'get_object',
            Params={'Bucket': R2_BUCKET, 'Key': filename},
            ExpiresIn=LINK_EXPIRY
        )
        return render_template(
            "video_view.html",
            filename=filename,
            file_url=signed_url,
            download_url=signed_url,
            delete_url=del_url,
            random_id=random_id,
            request=request
        )
    except Exception as e:
        app.logger.error(f"Video streaming error: {e}")
        return "Error generating video link", 500

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
