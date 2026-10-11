package com.krakentrade.mobile

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MarketIndicatorCalculatorTest {
    @Test fun risingMarketProducesUpTrend() {
        val candles = (0 until 40).map { i ->
            val close = 1.0 + i * 0.01
            Candle(
                timeEpochSeconds = i.toLong(),
                open = close - 0.005,
                high = close + 0.01,
                low = close - 0.01,
                close = close,
                vwap = close,
                volume = 100.0,
                tradeCount = 10
            )
        }
        val indicators = MarketIndicatorCalculator.calculate(candles)
        assertEquals(Trend.UP, indicators.trend)
        assertTrue(indicators.atr > 0.0)
        assertTrue(indicators.emaFast > indicators.emaSlow)
    }
}
