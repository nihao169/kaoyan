"""Text matching shared by teaching and personal source citations."""
import re


def quote_offset(source: str, quote: str, *, ignore_whitespace: bool = False) -> int:
    if ignore_whitespace:
        source = re.sub(r'\s+', '', source)
        quote = re.sub(r'\s+', '', quote)
    return source.find(quote) if quote else -1
