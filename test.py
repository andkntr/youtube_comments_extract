import pandas as pd
import yfinance as yf
import mplfinance as mpf
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# Define the stock symbol and date range
symbol = "AAPL"
start_date = "2023-01-01"
end_date = "2023-12-31"

# Fetch the stock data using the modified method
aapl = yf.Ticker(symbol)
data = aapl.history(start=start_date, end=end_date)

# Calculate moving averages
data['MA20'] = data['Close'].rolling(window=20).mean()
data['MA50'] = data['Close'].rolling(window=50).mean()

# Calculate MACD
data['EMA12'] = data['Close'].ewm(span=12, adjust=False).mean()
data['EMA26'] = data['Close'].ewm(span=26, adjust=False).mean()
data['MACD'] = data['EMA12'] - data['EMA26']
data['Signal_Line'] = data['MACD'].ewm(span=9, adjust=False).mean()

# Calculate stochastic oscillator
high_14 = data['High'].rolling(window=14).max()
low_14 = data['Low'].rolling(window=14).min()
data['%K'] = 100 * (data['Close'] - low_14) / (high_14 - low_14)
data['%D'] = data['%K'].rolling(window=3).mean()

# Set up mplfinance style
mpf_style = mpf.make_mpf_style(base_mpf_style='yahoo', rc={'font.size': 10})

# Create subplots for candlestick, volume, MACD, and stochastic oscillator
fig = mpf.figure(style=mpf_style, figsize=(12, 10))
ax_main = fig.add_subplot(4, 1, 1)  # Candlestick chart
ax_volume = fig.add_subplot(4, 1, 2, sharex=ax_main)  # Volume chart
ax_macd = fig.add_subplot(4, 1, 3, sharex=ax_main)  # MACD chart
ax_stochastic = fig.add_subplot(4, 1, 4, sharex=ax_main)  # Stochastic oscillator chart

# Plot candlestick chart with moving averages
mpf.plot(
    data,
    type='candle',
    mav=(20, 50),
    ax=ax_main,
    volume=ax_volume,  # Specify the volume subplot
    show_nontrading=True
)

# Plot MACD
ax_macd.plot(data.index, data['MACD'], label='MACD', color='blue')
ax_macd.plot(data.index, data['Signal_Line'], label='Signal Line', color='orange')
ax_macd.axhline(0, color='gray', linewidth=0.5, linestyle='--')
ax_macd.legend(loc='upper left')
ax_macd.set_ylabel("MACD")

# Plot stochastic oscillator
ax_stochastic.plot(data.index, data['%K'], label='%K', color='blue')
ax_stochastic.plot(data.index, data['%D'], label='%D', color='orange')
ax_stochastic.axhline(80, color='gray', linewidth=0.5, linestyle='--', alpha=0.7)
ax_stochastic.axhline(20, color='gray', linewidth=0.5, linestyle='--', alpha=0.7)
ax_stochastic.legend(loc='upper left')
ax_stochastic.set_ylabel("Stochastic")

# Format x-axis dates
ax_stochastic.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
plt.xticks(rotation=45)

# Show the plot
plt.tight_layout()
plt.show()
