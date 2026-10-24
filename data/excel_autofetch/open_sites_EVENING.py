import webbrowser
import time

websites = [
    "https://www.moneycontrol.com/indian-indices/NIFTY-50-9.html",
    "https://www.google.com/finance/beta/quote/INDIA_VIX:INDEXNSE",
    "https://web.stockedge.com/fii-activity",
    "https://www.niftytrader.in/live-nifty-open-interest",
    "https://stockmojo.in/open-interest/nifty",
    "https://www.moneycontrol.com/stocksmarketsindia/heat-map-advance-decline-ratio-nse-bse",
    "https://in.investing.com/commodities/brent-oil",
    "https://www.live-rates.com/rates/usd-inr",
    "https://www.investing.com/rates-bonds/u.s.-10-year-bond-yield",
    "https://www.niftytrader.in/sector-analysis",
    "https://www.perplexity.ai/",
]

for site in websites:
    webbrowser.open(site)
    time.sleep(1)