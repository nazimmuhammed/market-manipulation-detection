from app.ml.plugins.base import Detector

class RoundNumberDetector(Detector):
    name = "round_number_bias"
    description = "Flags trades clustering suspiciously around round price levels."

    def score(self, ticker, tick, history):
        price = tick["close"]
        remainder = price % 10
        if remainder < 0.5 or remainder > 9.5:
            return 40.0
        return 0.0