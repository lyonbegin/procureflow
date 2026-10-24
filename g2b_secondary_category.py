"""Parser for clearly labeled 10-digit G2B detail category codes on public notice pages.
Classification evidence source is preserved separately from official records.
"""
import re
from html.parser import HTMLParser

class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts=[]
    def handle_data(self,data):
        self.parts.append(data)

def parse_category_labels(html, bid_no):
    p=TextParser()
    p.feed(html)
    text=" ".join(p.parts)
    if bid_no not in text:
        return []
    matches=re.findall(r"분류\s*(?:\|\s*)?[^()]{1,65}\((\d{10})\)",text)
    return sorted(set(matches))
