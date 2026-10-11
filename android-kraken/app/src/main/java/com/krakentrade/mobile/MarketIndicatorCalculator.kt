package com.krakentrade.mobile

object MarketIndicatorCalculator {
    fun calculate(
        candles: List<Candle>,
        fastPeriod: Int = 9,
        slowPeriod: Int = 21,
        atrPeriod: Int = 14
    ): MarketIndicators {
        require(candles.size >= maxOf(fastPeriod, slowPeriod, atrPeriod + 1)) {
            "Za mało świec do obliczenia wskaźników"
        }
        require(fastPeriod > 1 && slowPeriod > fastPeriod && atrPeriod > 1)

        val closes = candles.map { it.close }
        return MarketIndicators(
            lastClose = closes.last(),
            emaFast = ema(closes, fastPeriod),
            emaSlow = ema(closes, slowPeriod),
            atr = atr(candles, atrPeriod)
        )
    }

    internal fun ema(values: List<Double>, period: Int): Double {
        require(values.size >= period)
        val multiplier = 2.0 / (period + 1.0)
        var value = values.take(period).average()
        for (i in period until values.size) {
            value = (values[i] - value) * multiplier + value
        }
        return value
    }

    internal fun atr(candles: List<Candle>, period: Int): Double {
        require(candles.size >= period + 1)
        val trueRanges = mutableListOf<Double>()
        for (i in 1 until candles.size) {
            val current = candles[i]
            val previousClose = candles[i - 1].close
            val tr = maxOf(
                current.high - current.low,
                kotlin.math.abs(current.high - previousClose),
                kotlin.math.abs(current.low - previousClose)
            )
            trueRanges += tr
        }
        return trueRanges.takeLast(period).average()
    }
}
