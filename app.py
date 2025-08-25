import os
import re
import io
import csv
from flask import Flask, request, render_template, send_file
from googleapiclient.discovery import build

app = Flask(__name__)

"""
トップページ
"""
@app.route("/")
def index():
    projects = [
    {
        "name": "YouTubeコメント抽出",
        "description": "指定したYouTube動画のコメント（返信含む）をCSVでダウンロードできます。",
        "url": "/comments"
    }]
    return render_template("index.html", projects=projects)




"""
YOUTUBEコメント抽出機能
"""

# ---- YouTube API キー ----
API_KEY = os.environ.get("API_KEY")
if not API_KEY:
    raise ValueError("環境変数 API_KEY が設定されていません")

youtube = build("youtube", "v3", developerKey=API_KEY)


# ---- YouTubeのコメント取得関数 ----
def get_video_id(url):
    match = re.search(r"v=([a-zA-Z0-9_-]{11})", url)
    return match.group(1) if match else None


def fetch_all_comments(video_id, max_pages=10):
    comments = []
    page_token = None
    page_count = 0

    while True:
        request = youtube.commentThreads().list(
            part="snippet,replies",
            videoId=video_id,
            maxResults=100,
            pageToken=page_token,
            textFormat="plainText"
        )
        response = request.execute()

        for item in response.get("items", []):
            top = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "author": top["authorDisplayName"],
                "text": top["textOriginal"],
                "likes": top["likeCount"],
                "published": top["publishedAt"],
                "reply_to": None
            })

            # 返信コメントも追加
            if "replies" in item:
                for reply in item["replies"]["comments"]:
                    r = reply["snippet"]
                    comments.append({
                        "author": r["authorDisplayName"],
                        "text": r["textOriginal"],
                        "likes": r["likeCount"],
                        "published": r["publishedAt"],
                        "reply_to": top["authorDisplayName"]
                    })

        page_token = response.get("nextPageToken")
        page_count += 1
        if not page_token or page_count >= max_pages:
            break

    return comments


# 動画詳細取得
def get_video_details(video_id):
    request = youtube.videos().list(part="snippet", id=video_id)
    response = request.execute()
    if response["items"]:
        s = response["items"][0]["snippet"]
        return s["channelTitle"], s["title"]
    return "UnknownChannel", "UnknownTitle"


# ファイル名に使えない文字を置換
def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', '_', name)


# ---- ルート ----
@app.route("/comments", methods=["GET", "POST"])
def comments():
    if request.method == "POST":
        url = request.form["url"]
        video_id = get_video_id(url)
        if not video_id:
            return "無効なURLです"

        comments = fetch_all_comments(video_id)

        # ---- pandas の代わりに csv.writer でCSV出力 ----
        headers = ["投稿者", "コメント本文", "高評価数", "投稿日時", "返信先"]
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        for c in comments:
            writer.writerow({
                "投稿者": c["author"],
                "コメント本文": c["text"],
                "高評価数": c["likes"],
                "投稿日時": c["published"],
                "返信先": c["reply_to"] or ""
            })
        output.seek(0)

        # ファイル名を「チャンネル名_動画タイトル.csv」にする
        channel, title = get_video_details(video_id)
        filename = f"{sanitize_filename(channel)}_{sanitize_filename(title)}.csv"

        return send_file(
            io.BytesIO(output.getvalue().encode("utf-8-sig")),
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename
        )

    return render_template("comments.html")


if __name__ == "__main__":
    app.run(debug=True)
