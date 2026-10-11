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

data class PairRules(
    val internalId: String,
    val altName: String,
    val displayName: String,
    val baseAsset: String,
    val quoteAsset: String,
    val orderMin: Double,
    val costMin: Double,
    val tickSize: Double,
    val pairDecimals: Int,
    val lotDecimals: Int,
    val status: String
) {
    val isOnline: Boolean get() = status.equals("online", ignoreCase = true)
}

interface PairRulesGateway {
    override suspend fun fetchPair(pair: String): Result<PairRules>
}

class KrakenAssetPairsApi(
    private val baseUrl: String = "https://api.kraken.com"
) : PairRulesGateway {
    private val json = Json { ignoreUnknownKeys = true }

    suspend fun fetchPair(pair: String): Result<PairRules> = withContext(Dispatchers.IO) {
        runCatching {
            val encoded = URLEncoder.encode(pair, StandardCharsets.UTF_8.name())
            val connection = URI.create("$baseUrl/0/public/AssetPairs?pair=$encoded")
                .toURL().openConnection() as HttpURLConnection
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
                parseSinglePair(raw)
            } finally {
                connection.disconnect()
            }
        }
    }

    internal fun parseSinglePair(raw: String): PairRules {
        val root = json.parseToJsonElement(raw).jsonObject
        val errors = root["error"]?.jsonArray?.map { it.jsonPrimitive.content }.orEmpty()
            .filter { it.isNotBlank() }
        if (errors.isNotEmpty()) error(errors.joinToString("; "))

        val result = root["result"]?.jsonObject ?: error("Brak result w AssetPairs")
        val (internalId, infoElement) = result.entries.firstOrNull()
            ?: error("Nie znaleziono pary")
        val info = infoElement.jsonObject

        return PairRules(
            internalId = internalId,
            altName = info["altname"]?.jsonPrimitive?.content ?: internalId,
            displayName = info["wsname"]?.jsonPrimitive?.content ?: internalId,
            baseAsset = info["base"]?.jsonPrimitive?.content ?: error("Brak base"),
            quoteAsset = info["quote"]?.jsonPrimitive?.content ?: error("Brak quote"),
            orderMin = info["ordermin"]?.jsonPrimitive?.content?.toDoubleOrNull() ?: 0.0,
            costMin = info["costmin"]?.jsonPrimitive?.content?.toDoubleOrNull() ?: 0.0,
            tickSize = info["tick_size"]?.jsonPrimitive?.content?.toDoubleOrNull() ?: 0.0,
            pairDecimals = info["pair_decimals"]?.jsonPrimitive?.content?.toIntOrNull() ?: 8,
            lotDecimals = info["lot_decimals"]?.jsonPrimitive?.content?.toIntOrNull() ?: 8,
            status = info["status"]?.jsonPrimitive?.content ?: "unknown"
        )
    }
}
