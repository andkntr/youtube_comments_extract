import os
import unicodedata
from flask import Flask, request, render_template, jsonify, send_file
import pandas as pd
import folium
from geopy.geocoders import OpenCage
from time import sleep
import re
import time
from rapidfuzz import process
import yfinance as yf
import mplfinance as mpf
import plotly.graph_objects as go
from datetime import datetime
from plotly.subplots import make_subplots
from googleapiclient.discovery import build
import io 
import os





app = Flask(__name__)

"""
トップページ
"""
@app.route("/")
def index():
    projects = [
        {"name": "ボタン型チャットボット", "description": "多階層の質問を事前にトレーニングし、選択肢を基に回答するチャットボットシステム", "url": "/chatbot_button"},
        {"name": "自由回答型チャットボット", "description": "質問と回答の組み合わせを事前にトレーニングし、ユーザーが入力した質問に回答するチャットボットシステム", "url": "/chatbot_free"},
        {"name": "地図ピン", "description": "住所を一括アップロードし、地図上にピンを指すツール", "url": "/map"},
    ]
    return render_template("index.html", projects=projects)


"""
地図にピン止めるやつ
"""
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# OpenCage APIキーを設定
OPEN_CAGE_API_KEY = "26d4b1d3c23645ea85970af13e96f718"
geolocator = OpenCage(api_key=OPEN_CAGE_API_KEY, timeout=5)

def clean_address(address):
    """住所をフォーマットして整える関数"""
    import unicodedata

    # NoneまたはNaNの場合に空文字列に変換
    address = str(address) if pd.notna(address) else ""

    # 全角を半角に変換
    address = unicodedata.normalize("NFKC", address)

    # 不要なスペース削除
    address = address.replace(" ", "").replace("　", "")
    # 丁目、番地を "-" に置き換え
    address = address.replace("丁目", "-").replace("番地", "-")
    # "号" を削除
    address = address.replace("号", "")

    return address.strip()

def generate_map(file_path):
    """地図を生成する関数"""
    if file_path.endswith(".csv"):
        data = pd.read_csv(file_path, header=0)
    elif file_path.endswith(".xlsx"):
        data = pd.read_excel(file_path, header=0)
    else:
        raise ValueError("CSVまたはExcelファイルをアップロードしてください。")

    # 1列目: 住所
    addresses = data.iloc[:, 0]
    map_obj = folium.Map(location=[35.0, 135.0], tiles="CartoDB positron", zoom_start=10)
    bounds = []

    for raw_address in addresses:
        full_address = clean_address(raw_address)
        retries = 3  # 最大リトライ回数
        for attempt in range(retries):
            try:
                location = geolocator.geocode(full_address)
                if location:
                    bounds.append((location.latitude, location.longitude))
                    folium.Marker(
                        location=[location.latitude, location.longitude],
                        popup=full_address,
                        tooltip=full_address,
                        icon=folium.Icon(color="blue", icon="info-sign")
                    ).add_to(map_obj)
                else:
                    print(f"住所が見つかりませんでした: {full_address}")
                break  # 成功したらループを抜ける
            except Exception as e:
                print(f"エラーが発生しました (住所: {full_address}, 試行回数: {attempt + 1}): {e}")
                if attempt < retries - 1:
                    time.sleep(2)  # 次の試行まで2秒待つ
                else:
                    print(f"リトライに失敗しました: {full_address}")
        # 各住所の処理間で待機時間を追加（例えば2秒）
        time.sleep(1)

    if bounds:
        map_obj.fit_bounds(bounds)
    return map_obj._repr_html_()

@app.route("/map", methods=["GET", "POST"])
def upload_and_display_map():
    if request.method == "POST":
        file = request.files["file"]
        if file:
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
            file.save(file_path)
            try:
                map_html = generate_map(file_path)
            except Exception as e:
                return f"エラーが発生しました: {e}"
            return render_template("map.html", map_html=map_html)
    return render_template("upload.html")

"""
Chatbot project
"""

# 自由記述データを読み込む
qa_data_file_free = "/Users/andkntr/python/microproject/qa_data.xlsx"
try:
    df_free = pd.read_excel(qa_data_file_free).fillna("")  # 欠損値を空文字列に置き換え
    qa_data_free = dict(zip(df_free['質問'], df_free['回答内容']))  # 質問と回答を辞書に変換
except Exception as e:
    print(f"自由記述データの読み込みに失敗しました: {e}")

@app.route('/chatbot_free', methods=['GET', 'POST'])
def chatbot_free():
    """入力を受けて回答を同じページで出力する"""
    user_input = ''
    response = ''

    if request.method == 'POST':
        user_input = request.form.get('message', "").strip()  # フォームからユーザー入力を取得
        response = "申し訳ありません、その質問にはお答えできません。"

        # 類似度検索
        try:
            result = process.extractOne(user_input, qa_data_free.keys())
            if result:  # 結果が存在する場合のみ処理
                closest_match, score = result[0], result[1]  # 必要な2つの値を取得
                if score > 70:  # スコアが60%以上の場合のみ採用
                    response = qa_data_free[closest_match]
        except Exception as e:
            print(f"自由記述エラー: {e}")
            response = f"エラーが発生しました: {str(e)}"

    # 初期画面または回答を含む画面をレンダリング
    return render_template('chatbot_free.html', user_message=user_input, bot_response=response)

"""
ボタン型のチャットボット
"""
# エクセルデータを読み込む関数
def load_qa_data(file_path):
    try:
        df = pd.read_excel(file_path)
        # 質問 -> {サブ質問 -> 回答内容} の階層構造を作成
        qa_data = {}
        for _, row in df.iterrows():
            main_question = row['質問']
            sub_question = row['サブ質問']
            answer = row['回答内容']
            if main_question not in qa_data:
                qa_data[main_question] = {}
            qa_data[main_question][sub_question] = answer
        print(qa_data)
        return qa_data
    except Exception as e:
        print(f"エクセルデータの読み込みに失敗しました: {e}")
        return {}


# エクセルデータを読み込み
qa_data = load_qa_data('/Users/andkntr/python/microproject/qa_data3.xlsx')


@app.route("/chatbot_button")
def chatbot_button():
    # メイン質問をフロントエンドに渡す
    main_questions = list(qa_data.keys())
    return render_template("chatbot_button.html", questions=main_questions)

@app.route("/chatbot_button/get_sub_questions", methods=["POST"])
def get_sub_questions():
    main_question = request.json.get("main_question")
    sub_questions = list(qa_data.get(main_question, {}).keys())
    return jsonify({"sub_questions": sub_questions})

@app.route("/chatbot_button/get_response", methods=["POST"])
def get_response():
    main_question = request.json.get("main_question")
    sub_question = request.json.get("sub_question")
    response = qa_data.get(main_question, {}).get(sub_question, "すみません、それはよくわかりません。")
    return jsonify({"response": response})

"""
Stock Chart Project
"""

# Ensure uploads folder exists
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

@app.route("/stocks", methods=["GET", "POST"])
def stock_dashboard():
    analysis = {}
    stock_info = {}
    stock_data = pd.DataFrame()
    candlestick_chart = None
    if request.method == "POST":
        ticker = request.form.get("ticker", "").upper().strip()
        start_date = request.form.get("start_date", "").strip()
        end_date = request.form.get("end_date", "").strip()

        # Default to past 3 months if dates are not provided
        if not start_date:
            start_date = (datetime.now() - pd.DateOffset(months=3)).strftime('%Y-%m-%d')
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')

        if ticker:
            try:
                aapl = yf.Ticker(ticker)
                stock_data = aapl.history(start=start_date, end=end_date)

                # Remove weekends and holidays
                stock_data = stock_data[stock_data.index.dayofweek < 5]

                # Fetch basic stock info
                current_price = stock_data['Close'].iloc[-1]
                previous_close = stock_data['Close'].iloc[-2]
                change = current_price - previous_close
                change_percent = (change / previous_close) * 100

                stock_info = {
                    "company_name": aapl.info.get("longName", "N/A"),
                    "sector": aapl.info.get("sector", "N/A"),
                    "market_cap": f"{aapl.info.get('marketCap', 'N/A'):,}" if isinstance(aapl.info.get('marketCap'), int) else 'N/A',
                    "dividend_yield": f"{aapl.info.get('dividendYield', 'N/A') * 100:.2f}%" if isinstance(aapl.info.get('dividendYield'), (int, float)) else 'N/A',
                    "current_price": f"{current_price:.2f}",
                    "change": change,
                    "change_percent": change_percent,
                }

                # Generate candlestick chart
                candlestick_chart = generate_candlestick_chart(stock_data)

                # Perform technical analysis
                analysis = perform_technical_analysis(stock_data)
            except Exception as e:
                return f"Error: {str(e)}"

    return render_template("stocks.html", analysis=analysis, stock_info=stock_info, stock_data=stock_data, candlestick_chart=candlestick_chart)

def generate_candlestick_chart(stock_data):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.02, row_heights=[0.7, 0.3])

    # Add candlestick chart
    fig.add_trace(go.Candlestick(
        x=stock_data.index,
        open=stock_data['Open'],
        high=stock_data['High'],
        low=stock_data['Low'],
        close=stock_data['Close'],
        name="Price"
    ), row=1, col=1)

    # Add moving averages
    stock_data['SMA_5'] = stock_data['Close'].rolling(window=5).mean()
    stock_data['SMA_25'] = stock_data['Close'].rolling(window=25).mean()
    stock_data['SMA_75'] = stock_data['Close'].rolling(window=75).mean()
    fig.add_trace(go.Scatter(
        x=stock_data.index, y=stock_data['SMA_5'],
        mode='lines', name='SMA 5',
        line=dict(color='green')
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=stock_data.index, y=stock_data['SMA_25'],
        mode='lines', name='SMA 25',
        line=dict(color='blue')
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=stock_data.index, y=stock_data['SMA_75'],
        mode='lines', name='SMA 75',
        line=dict(color='orange')
    ), row=1, col=1)

    # Add volume bar chart
    fig.add_trace(go.Bar(
        x=stock_data.index, y=stock_data['Volume'],
        name="Volume", marker=dict(color='lightgray')
    ), row=2, col=1)

    fig.update_layout(
        title="Candlestick Chart with Moving Averages and Volume",
        xaxis_title="Date",
        yaxis_title="Price",
        xaxis2_title="Date",
        yaxis2_title="Volume",
        template="plotly_white"
    )
    return fig.to_html(full_html=False)

def perform_technical_analysis(stock_data):
    analysis = {}
    stock_data["SMA_5"] = stock_data["Close"].rolling(window=5).mean()
    stock_data["SMA_25"] = stock_data["Close"].rolling(window=25).mean()
    stock_data["SMA_75"] = stock_data["Close"].rolling(window=75).mean()

    # RSI Calculation
    delta = stock_data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    stock_data['RSI'] = 100 - (100 / (1 + rs))

    # Determine Buy/Sell based on RSI
    last_rsi = stock_data['RSI'].iloc[-1]
    if last_rsi < 30:
        analysis['Recommendation'] = 'Buy'
    elif last_rsi > 70:
        analysis['Recommendation'] = 'Sell'
    else:
        analysis['Recommendation'] = 'Hold'

    # Add key indicators to analysis
    analysis['RSI'] = f"{last_rsi:.1f}"
    analysis['SMA_5'] = f"{stock_data['SMA_5'].iloc[-1]:.2f}"
    analysis['SMA_25'] = f"{stock_data['SMA_25'].iloc[-1]:.2f}"
    analysis['SMA_75'] = f"{stock_data['SMA_75'].iloc[-1]:.2f}"

    # Risk Assessment using ATR
    stock_data['ATR'] = (stock_data['High'] - stock_data['Low']).rolling(window=14).mean()
    analysis['ATR'] = stock_data['ATR'].iloc[-1]

    return analysis



"""
YOUTUBEコメント抽出機能
"""

# ---- YouTube API キー ----
API_KEY = os.environ.get("API_KEY")

if not API_KEY:
    raise ValueError("環境変数 API_KEY が設定されていません")

youtube = build("youtube", "v3", developerKey=API_KEY)
youtube = build("youtube", "v3", developerKey=API_KEY)

# ---- YouTubeのコメント取得関数 ----
def get_video_id(url):
    match = re.search(r"v=([a-zA-Z0-9_-]{11})", url)
    if match:
        return match.group(1)
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
                "reply_to": None  # トップレベルなので None
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
                        "reply_to": top["authorDisplayName"]  # 誰への返信か
                    })

        # ページ送り
        page_token = response.get("nextPageToken")
        page_count += 1
        if not page_token or page_count >= max_pages:
            break

    return comments

# YouTube動画の詳細を取得する関数
def get_video_details(video_id):
    # videoId を指定して videos().list を叩くと動画情報が取れる
    request = youtube.videos().list(
        part="snippet",
        id=video_id
    )
    response = request.execute()
    if "items" in response and len(response["items"]) > 0:
        snippet = response["items"][0]["snippet"]
        # チャンネル名と動画タイトルを返す
        return snippet["channelTitle"], snippet["title"]
    # 取得できなかった場合のフォールバック
    return "UnknownChannel", "UnknownTitle"


# ファイル名に使えない文字を置換する関数
def sanitize_filename(name: str) -> str:
    # Windows / macOS / Linux で禁止されている記号を「_」に置換
    return re.sub(r'[\\/*?:"<>|]', '_', name)


# ---- ルート ----
@app.route("/comments", methods=["GET", "POST"])
def comments():
    if request.method == "POST":
        url = request.form["url"]
        # URLから videoId を抽出（例: https://youtu.be/xxxxxx → xxxxxxx）
        video_id = get_video_id(url)
        if not video_id:
            return "無効なURLです"

        # コメント（トップ＋返信）をすべて取得
        comments = fetch_all_comments(video_id)

        # pandas DataFrame に変換
        df = pd.DataFrame(comments)

        # 列名を日本語に変換してCSVを読みやすくする
        df = df.rename(columns={
            "author": "投稿者",
            "text": "コメント本文",
            "likes": "高評価数",
            "published": "投稿日時",
            "reply_to": "返信先"
        })

        # CSVを一時的にメモリ上に書き出す
        output = io.StringIO()
        df.to_csv(output, index=False, encoding="utf-8-sig")
        output.seek(0)

        # 動画の「チャンネル名」と「タイトル」を取得してファイル名にする
        channel, title = get_video_details(video_id)
        filename = f"{sanitize_filename(channel)}_{sanitize_filename(title)}.csv"

        # CSVファイルをダウンロードさせる
        return send_file(
            io.BytesIO(output.getvalue().encode("utf-8-sig")),
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename
        )

    # 初回アクセス時はフォームを表示
    return render_template("comments.html")


if __name__ == "__main__":
    app.run(debug=True)
