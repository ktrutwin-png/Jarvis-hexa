package com.krakentrade.mobile

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

class KrakenBalanceApi(
    private val transport: KrakenPrivateTransport
) {
    private val json = Json { ignoreUnknownKeys = true }

    suspend fun fetchBalances(): Result<Map<String, Double>> =
        transport.post("/0/private/Balance", emptyMap()).flatMap(::parseBalances)

    internal fun parseBalances(raw: String): Result<Map<String, Double>> = runCatching {
        KrakenResponse.requireSuccess(raw).getOrThrow()
        val root = json.parseToJsonElement(raw).jsonObject
        val result = root["result"]?.jsonObject ?: error("Brak result w Balance")
        result.mapValues { (_, value) ->
            value.jsonPrimitive.content.toDoubleOrNull() ?: 0.0
        }
    }

    fun capacityForPair(
        pairRules: PairRules,
        balances: Map<String, Double>,
        lastPrice: Double
    ): AccountCapacity {
        require(lastPrice > 0.0)
        val base = balances[pairRules.baseAsset] ?: 0.0
        val quote = balances[pairRules.quoteAsset] ?: 0.0
        return AccountCapacity(
            quoteBalance = quote,
            baseBalance = base,
            accountEquityQuote = quote + base * lastPrice
        )
    }

    private inline fun <T, R> Result<T>.flatMap(transform: (T) -> Result<R>): Result<R> =
        fold(onSuccess = transform, onFailure = { Result.failure(it) })
}
