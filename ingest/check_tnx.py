# check_tnx.py
# One-time check: what does ^TNX actually return right now?

import yfinance as yf

h = yf.Ticker("^TNX").history(period="5d")
print(h[["Open", "High", "Low", "Close"]])