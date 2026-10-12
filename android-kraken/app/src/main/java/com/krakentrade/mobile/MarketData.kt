package com.krakentrade.mobile

data class Candle(
    val timeEpochSeconds: Long,
    val open: Double,
    val high: Double,
    val low: Double,
    val close: Double,
    val vwap: Double,
    val volume: Double,
    val tradeCount: Int
)

data class MarketIndicators(
    val lastClose: Double,
    val emaFast: Double,
    val emaSlow: Double,
    val atr: Double
) {
    val trend: Trend
        get() = when {
            emaFast > emaSlow -> Trend.UP
            emaFast < emaSlow -> Trend.DOWN
            else -> Trend.FLAT
    }
}

enum class Trend { UP, DOWN, FLAT }
