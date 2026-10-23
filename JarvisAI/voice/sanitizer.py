"""
Jarvis AI Pro - Speech Sanitizer
Pre-processes LLM text before passing to TTS, stripping unpronounceable characters,
markdown artifacts, and translating technical notation into natural spoken English.
"""

import re

class SpeechSanitizer:
    @staticmethod
    def clean_for_speech(text: str) -> str:
        if not text:
            return ""

        # Remove markdown code blocks and replace with brief vocal indicator
        text = re.sub(r"```[\s\S]*?```", " [Code displayed on screen] ", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)

        # Remove markdown headers, bold, italics, strikethroughs, lists
        text = re.sub(r"#+\s*", "", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"~~([^~]+)~~", r"\1", text)
        text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)

        # Replace URLs with speakable phrases
        text = re.sub(r"https?://\S+|www\.\S+", "the requested link", text)

        # Translate technical symbols into spoken English
        replacements = [
            (r"\b(\d+)%\b", r"\1 percent"),
            (r"\b(\d+)°C\b", r"\1 degrees Celsius"),
            (r"\b(\d+)°F\b", r"\1 degrees Fahrenheit"),
            (r"\b(\d+)km/h\b", r"\1 kilometers per hour"),
            (r"\b(\d+)mph\b", r"\1 miles per hour"),
            (r"\b(\d+)ms\b", r"\1 milliseconds"),
            (r"\b(\d+)GB\b", r"\1 gigabytes"),
            (r"\b(\d+)MB\b", r"\1 megabytes"),
            (r"&", " and "),
            (r"@", " at "),
            (r"\+", " plus "),
            (r"=", " equals "),
            (r"w/", "with"),
            (r"w/o", "without"),
        ]
        for pattern, repl in replacements:
            text = re.sub(pattern, repl, text, flags=re.IGNORECASE)

        # Remove emojis and unprintable symbols
        text = text.encode("ascii", "ignore").decode("ascii")

        # Collapse excess whitespace and return
        text = re.sub(r"\s+", " ", text).strip()
        return text
