"""Shared deterministic ticket extraction; this does not cluster activities."""
import re
TICKET_PATTERN = re.compile(r"\b([A-Z]{2,10}-[0-9]+)\b")

def extract_tickets(texts):
    return sorted({ticket for text in texts for ticket in TICKET_PATTERN.findall(text)})
