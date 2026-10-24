import webbrowser
import time

websites = [
    "https://www.moneycontrol.com/markets/global-indices/",
    "https://www.cnbc.com/quotes/US10Y",
    "https://in.investing.com/currencies/usd-inr",
    "https://www.moneycontrol.com/live-index/gift-nifty?symbol=in;gsx",
]

for site in websites:
    webbrowser.open(site)
    time.sleep(1)
    