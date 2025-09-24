import os
import random
import string
import time
import threading
import logging
import json
import io
from flask import Flask, request, render_template, url_for, jsonify
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
LINK_EXPIRY = 1440 * 60  # 24 hours in seconds

# --- File links persistence in R2 ---
LINKS_FILE_KEY = "file_links.json"
file_links = {}

from botocore.exceptions import ClientError

def load_links():
    global file_links
    try:
        obj = r2.get_object(Bucket=R2_BUCKET, Key=LINKS_FILE_KEY)
        data = obj["Body"].read().decode("utf-8")
        file_links = json.loads(data)
        app.logger.info("Loaded file_links.json from R2")
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            app.logger.info("No existing file_links.json in R2, starting fresh")
            file_links = {}
        else:
            app.logger.error(f"Error loading file_links.json: {e}")
            file_links = {}
    except Exception as e:
        app.logger.error(f"Unexpected error loading file_links.json: {e}")
        file_links = {}

def save_links():
    try:
        data = json.dumps(file_links)
        r2.put_object(Bucket=R2_BUCKET, Key=LINKS_FILE_KEY, Body=data.encode("utf-8"))
        app.logger.info("Updated file_links.json in R2")
    except Exception as e:
        app.logger.error(f"Error saving file_links.json: {e}")

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
        save_links()

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
        save_links()
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
    save_links()
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
        save_links()

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
        save_links()
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

# --------------- LOG IN ROUTE ---------------

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    if username == os.getenv("UPLOAD_USER") and password == os.getenv("UPLOAD_PASS"):
        return jsonify({"success": True})
    return jsonify({"success": False}), 401

# ------------------- Cleaner -------------------

def cleanup_expired_files():
    while True:
        now = time.time()
        expired_keys = [key for key, info in list(file_links.items())
                        if now - info["time"] > LINK_EXPIRY]

        for key in expired_keys:
            filename = file_links[key]["filename"]
            try:
                r2.delete_object(Bucket=R2_BUCKET, Key=filename)
                app.logger.info(f"Auto-deleted expired file: {filename}")
            except Exception as e:
                app.logger.error(f"Error auto-deleting {filename}: {e}")

            file_links.pop(key, None)

        if expired_keys:
            save_links()

        time.sleep(60)

# --- Load state from R2 on startup ---
with app.app_context():
    load_links()

threading.Thread(target=cleanup_expired_files, daemon=True).start()

if __name__ == "__main__":
    app.run(debug=True)
