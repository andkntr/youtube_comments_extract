import folium

# 住所と座標のリスト
locations = [
    {"address": "〒545-0052 大阪府大阪市阿倍野区阿倍野筋４丁目１９−１１８", "coordinates": [34.637567, 135.514004]},
    {"address": "〒545-0052 大阪府大阪市阿倍野区阿倍野筋３丁目１０−１−１００", "coordinates": [34.646449, 135.512646]},
]

# 地図の中心座標を計算
center_lat = sum([loc["coordinates"][0] for loc in locations]) / len(locations)
center_lon = sum([loc["coordinates"][1] for loc in locations]) / len(locations)

# CartoDB Positronスタイルの地図を作成
map_cartodb_positron = folium.Map(
    location=[center_lat, center_lon],
    tiles="CartoDB positron",  # 明るいトーンの地図
    attr="CartoDB",
    zoom_start=15
)

# ピンを追加
for loc in locations:
    folium.Marker(
        location=loc["coordinates"],
        popup=loc["address"],  # ピンをクリックした際に表示する住所
        tooltip=loc["address"],  # ツールチップに住所を表示
        icon=folium.Icon(color="blue", icon="info-sign")  # 青色アイコン
    ).add_to(map_cartodb_positron)

# 地図をHTMLファイルとして保存
map_file_path = "cartodb_positron_map.html"
map_cartodb_positron.save(map_file_path)

print(f"地図が作成されました: {map_file_path}")
