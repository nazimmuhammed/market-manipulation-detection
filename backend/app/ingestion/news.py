import requests
import xml.etree.ElementTree as ET

COMPANY_NAMES = {
    "RELIANCE": "Reliance Industries", "TCS": "Tata Consultancy Services",
    "INFY": "Infosys", "HDFCBANK": "HDFC Bank", "ADANIENT": "Adani Enterprises"
}

def fetch_real_headlines(ticker, max_headlines=5):
    query = COMPANY_NAMES.get(ticker, ticker)
    try:
        url = f"https://news.google.com/rss/search?q={requests.utils.quote(query + ' stock')}&hl=en-IN&gl=IN&ceid=IN:en"
        resp = requests.get(url, timeout=5)
        root = ET.fromstring(resp.content)
        headlines = [item.find("title").text for item in root.findall(".//item")[:max_headlines]]
        return headlines if headlines else None
    except Exception as e:
        print(f"News fetch failed for {ticker}: {e}")
        return None