package com.krakentrade.mobile

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URI
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

interface MarketDataGateway {
    suspend fun fetchOhlc(pair: String, intervalMinutes: Int = 5): Result<List<Candle>>
}

class KrakenPublicMarketApi(
    private val baseUrl: String = "https://api.kraken.com"
) : MarketDataGateway {
    private val json = Json { ignoreUnknownKeys = true }
    private val supportedIntervals = setOf(1, 5, 15, 30, 60, 240, 1440, 10080, 21600)

    override suspend fun fetchOhlc(pair: String, intervalMinutes: Int): Result<List<Candle>> =
        withContext(Dispatchers.IO) {
            runCatching {
                require(pair.isNotBlank()) { "Para nie może być pusta" }
                require(intervalMinutes in supportedIntervals) { "Nieobsługiwany interwał OHLC" }

                val encodedPair = URLEncoder.encode(pair, StandardCharsets.UTF_8.name())
                val url = URI.create(
                    "$baseUrl/0/public/OHLC?pair=$encodedPair&interval=$intervalMinutes&assetVersion=1"
                ).toURL()
                val connection = url.openConnection() as HttpURLConnection
                try {
                    connection.requestMethod = "GET"
                    connection.connectTimeout = 15_000
                    connection.readTimeout = 20_000

                    val status = connection.responseCode
                    val stream = if (status in 200..299) connection.inputStream else connection.errorStream
                    val raw = stream?.use { input ->
                        BufferedReader(InputStreamReader(input, StandardCharsets.UTF_8)).readText()
                    }.orEmpty()
                    if (status !in 200..299) error("Kraken HTTP $status: $raw")
                    parseOhlc(raw)
                } finally {
                    connection.disconnect()
                }
            }
        }

    internal fun parseOhlc(raw: String): List<Candle> {
        val root = json.parseToJsonElement(raw).jsonObject
        val errors = root["error"]?.jsonArray
            ?.map { it.jsonPrimitive.content }
            .orEmpty()
            .filter { it.isNotBlank() }
        if (errors.isNotEmpty()) error(errors.joinToString("; "))

        val result = root["result"]?.jsonObject ?: error("Brak result w odpowiedzi OHLC")
        val candleEntry = result.entries.firstOrNull { it.key != "last" }
            ?: error("Brak danych świec OHLC")

        val rows = candleEntry.value.jsonArray
        if (rows.isEmpty()) return emptyList()

        // Kraken zawsze zwraca ostatnią, jeszcze niezakończoną świecę.
        return rows.dropLast(1).map { element ->
            val row = element.jsonArray
            require(row.size >= 8) { "Nieprawidłowy format świecy OHLC" }
            Candle(
                timeEpochSeconds = row[0].jsonPrimitive.content.toLong(),
                open = row[1].jsonPrimitive.content.toDouble(),
                high = row[2].jsonPrimitive.content.toDouble(),
                low = row[3].jsonPrimitive.content.toDouble(),
                close = row[4].jsonPrimitive.content.toDouble(),
                vwap = row[5].jsonPrimitive.content.toDouble(),
                volume = row[6].jsonPrimitive.content.toDouble(),
                tradeCount = row[7].jsonPrimitive.content.toInt()
            )
        }
    }
}
