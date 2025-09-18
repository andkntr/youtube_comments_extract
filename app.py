import os
import re
import io
import csv
from flask import Flask, request, render_template, send_file
from googleapiclient.discovery import build
import statistics
import yt_dlp 
import tempfile
from flask import after_this_request, send_file, flash, redirect, url_for, Response

app = Flask(__name__)

"""
トップページ
"""
@app.route("/")
def index():
    projects = [
        {"name": "YouTubeコメント抽出", "description": "YouTubeのURLから、動画のコメント（返信含む）を抽出し、CSVで出力します。", "url": "/comments"},
        {"name": "YouTubeチャンネル分析", "description": "YouTubeのURLからチャンネルの公開サマリ＋直近動画の統計をCSVで出力します。", "url": "/channel-health"},
        {"name": "YouTube動画ダウンロード", "description": "YouTubeのURLを入力して解像度を選択し、映像＋音声／映像のみ／音声のみをダウンロードできます。", "url": "/download"},
    ]
    return render_template("index.html", projects=projects)


"""
robots.txt用
"""
@app.route("/robots.txt")
def robots():
    lines = [
        "User-agent: *",
        "Disallow:",
        "Sitemap: https://app.akitaken.tech/sitemap.xml"
    ]
    return Response("\n".join(lines), mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    pages = [
        {"loc": "https://app.akitaken.tech/"},
        {"loc": "https://app.akitaken.tech/comments"},
        {"loc": "https://app.akitaken.tech/channel-health"},
        {"loc": "https://app.akitaken.tech/download"},
    ]

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for page in pages:
        xml += "  <url>\n"
        xml += f"    <loc>{page['loc']}</loc>\n"
        xml += "  </url>\n"
    xml += "</urlset>"

    return Response(xml, mimetype="application/xml")



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
    """
    YouTube URLや短縮URLから videoId を抽出する
    """
    # 1) https://www.youtube.com/watch?v=XXXX
    m = re.search(r"v=([a-zA-Z0-9_-]{11})", url)
    if m:
        return m.group(1)

    # 2) https://youtu.be/XXXX 形式
    m = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", url)
    if m:
        return m.group(1)

    # 3) videoId 単体が渡された場合（直接UCや11桁ID）
    m = re.match(r"^[a-zA-Z0-9_-]{11}$", url)
    if m:
        return url

    return None


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


# =========================
# チャンネル健診（APIキーのみ）
# =========================
import csv

def extract_channel_id(raw: str):
    """チャンネルID/URL/@ハンドルを受け取り、channelId を返す"""
    s = raw.strip()

    # 1) そのまま channelId っぽい（UCから始まる24文字）
    m = re.match(r'^(UC[0-9A-Za-z_-]{22})$', s)
    if m:
        return m.group(1)

    # 2) URL の /channel/UCxxxx 形式
    m = re.search(r'/channel/(UC[0-9A-Za-z_-]{22})', s)
    if m:
        return m.group(1)

    # 3) @ハンドル（URL or 文字列）
    m = re.search(r'@([A-Za-z0-9._-]+)', s)
    if m:
        handle = m.group(1)
        # handle は channels.list で直接は引けないので search で取得
        res = youtube.search().list(
            part="snippet",
            q=f"@{handle}",
            type="channel",
            maxResults=1
        ).execute()
        items = res.get("items", [])
        if items:
            return items[0]["snippet"]["channelId"]

    # 4) その他（カスタムURL等） → 最後のセグメントでチャンネル検索
    tail = s.rstrip('/').split('/')[-1]
    if tail:
        res = youtube.search().list(
            part="snippet",
            q=tail,
            type="channel",
            maxResults=1
        ).execute()
        items = res.get("items", [])
        if items:
            return items[0]["snippet"]["channelId"]

    return None


def fetch_channel_summary(channel_id: str):
    """channels.list で公開サマリを取得"""
    res = youtube.channels().list(
        part="snippet,statistics",
        id=channel_id,
        maxResults=1
    ).execute()
    items = res.get("items", [])
    if not items:
        return None

    snip = items[0]["snippet"]
    stat = items[0]["statistics"]
    return {
        "channelId": channel_id,
        "チャンネル名": snip.get("title", ""),
        "説明": snip.get("description", ""),
        "国": snip.get("country", ""),
        "開設日": snip.get("publishedAt", ""),

        "登録者数": stat.get("subscriberCount", ""),
        "総再生回数": stat.get("viewCount", ""),
        "総動画数": stat.get("videoCount", "")
    }


def fetch_recent_videos(channel_id: str, max_results: int = 10):
    sres = youtube.search().list(
        part="snippet",
        channelId=channel_id,
        type="video",
        order="date",
        maxResults=min(max_results, 50)
    ).execute()
    ids = [it["id"]["videoId"] for it in sres.get("items", [])]

    videos = []
    for i in range(0, len(ids), 50):
        chunk = ids[i:i+50]
        vres = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(chunk)
        ).execute()
        for v in vres.get("items", []):
            vs = v.get("statistics", {})
            sn = v.get("snippet", {})
            videos.append({
                "動画ID": v.get("id", ""),
                "タイトル": sn.get("title", ""),
                "公開日": sn.get("publishedAt", ""),
                "再生数": int(vs.get("viewCount", 0)),
                "高評価数": int(vs.get("likeCount", 0)),
                "コメント数": int(vs.get("commentCount", 0)),
                "サムネイル": sn.get("thumbnails", {}).get("medium", {}).get("url", ""),
                "URL": f'https://www.youtube.com/watch?v={v.get("id","")}'
            })
    return videos



def format_number(n):
    try:
        return f"{int(n):,}"
    except Exception:
        return n

@app.route("/channel-health", methods=["GET", "POST"])
def channel_health():
    if request.method == "POST":
        raw = request.form.get("channel", "")
        channel_id = extract_channel_id(raw)
        if not channel_id:
            return "チャンネルが見つかりませんでした"

        summary = fetch_channel_summary(channel_id)
        if not summary:
            return "チャンネル情報の取得に失敗しました"

        videos = fetch_recent_videos(channel_id, max_results=10)

        # 平均・中央値
        views = [v["再生数"] for v in videos if v["再生数"] > 0]
        likes = [v["高評価数"] for v in videos if v["高評価数"] > 0]
        stats = {
            "平均再生数": int(statistics.mean(views)) if views else 0,
            "中央値再生数": int(statistics.median(views)) if views else 0,
            "平均いいね率": f"{(statistics.mean([l/v for l, v in zip(likes, views) if v > 0])*100):.2f}%" if views and likes else "N/A"
        }

        # 表示用に数値を整形
        summary["登録者数_fmt"] = format_number(summary.get("登録者数", 0))
        summary["総再生回数_fmt"] = format_number(summary.get("総再生回数", 0))
        summary["総動画数_fmt"] = format_number(summary.get("総動画数", 0))

        return render_template(
            "channel_health.html",
            summary=summary,
            videos=videos,
            stats=stats
        )

    # GET の場合
    return render_template("channel_health.html", summary=None, videos=None, stats=None)


# =========================================
# 動画ダウンロード（API不要）
# =========================================
def list_formats(video_url):
    with yt_dlp.YoutubeDL() as ydl:
        info = ydl.extract_info(video_url, download=False)
        formats = info.get("formats", [])
        results = []

        for f in formats:
            size = f.get("filesize")
            size_mb = round(size / 1024 / 1024, 2) if size else "不明"

            # 1. 映像＋音声が両方ある
            if f.get("vcodec") != "none" and f.get("acodec") != "none":
                results.append({
                    "タイプ": "映像＋音声",  # ✅ 表記を変更
                    "解像度": f.get("resolution"),
                    "サイズ(MB)": size_mb,
                    "download_code": f.get("format_id"),
                })
            elif f.get("vcodec") != "none" and f.get("acodec") == "none":
                results.append({
                    "タイプ": "映像のみ",
                    "解像度": f.get("resolution"),
                    "サイズ(MB)": size_mb,
                    "download_code": f.get("format_id"),
                })
            elif f.get("vcodec") == "none" and f.get("acodec") != "none":
                results.append({
                    "タイプ": "音声のみ",
                    "解像度": "音声のみ",
                    "サイズ(MB)": size_mb,
                    "download_code": f.get("format_id"),
                })

        # ✅ 映像＋音声を一番上に
        results.sort(key=lambda x: 0 if x["タイプ"] == "映像＋音声" else 1)
        return results



@app.route("/download", methods=["GET", "POST"])
def download():
    formats = None
    url = None
    if request.method == "POST":
        url = request.form.get("url")
        formats = list_formats(url)
    return render_template("download.html", formats=formats, url=url)


@app.route("/download-video", methods=["POST"])
def download_video():
    url = request.form.get("url")
    format_code = request.form.get("format_code")
    file_type = request.form.get("file_type")  # ← download.html で hidden input を追加する

    if not url or not format_code:
        return "url または format_code が足りません", 400

    # 拡張子を決定
    ext = "mp4"
    if file_type == "音声のみ":
        ext = "m4a"

    tmpdir = tempfile.mkdtemp(prefix="yt_")
    filepath = os.path.join(tmpdir, f"video.{ext}")

    ydl_opts = {
        "format": format_code,
        "outtmpl": filepath,   # ファイルパスを指定
        "quiet": True,
        "nopart": True,
    }

    # 映像（＋音声）の場合だけ merge_output_format を設定
    if ext == "mp4":
        ydl_opts["merge_output_format"] = "mp4"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "video")
    except Exception as e:
        return f"ダウンロードに失敗しました: {e}", 500

    @after_this_request
    def cleanup(response):
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
            os.rmdir(tmpdir)
        except Exception as e:
            app.logger.error(f"Cleanup failed: {e}")
        return response

    return send_file(
        filepath,
        as_attachment=True,
        download_name=f"{sanitize_filename(title)}.{ext}"
    )




if __name__ == "__main__":
    app.run(debug=True)
