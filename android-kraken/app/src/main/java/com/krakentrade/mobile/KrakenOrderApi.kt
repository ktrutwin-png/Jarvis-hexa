package com.krakentrade.mobile

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

enum class KrakenOrderStatus { PENDING, OPEN, CLOSED, CANCELED, EXPIRED, UNKNOWN }

data class KrakenOrderSnapshot(
    val txid: String,
    val status: KrakenOrderStatus,
    val volume: Double,
    val executedVolume: Double,
    val averagePrice: Double?
) {
    val isTerminal: Boolean
        get() = status in setOf(KrakenOrderStatus.CLOSED, KrakenOrderStatus.CANCELED, KrakenOrderStatus.EXPIRED)

    val isFilled: Boolean
        get() = status == KrakenOrderStatus.CLOSED && executedVolume > 0.0
}

class KrakenOrderApi(
    private val transport: KrakenPrivateTransport
) {
    private val json = Json { ignoreUnknownKeys = true }

    suspend fun validateEntryWithStopLoss(proposal: ExecutableProposal): Result<String> =
        addEntry(proposal, validateOnly = true)

    suspend fun placeEntryWithStopLoss(proposal: ExecutableProposal): Result<String> =
        addEntry(proposal, validateOnly = false)

    suspend fun placeTakeProfit(
        proposal: ExecutableProposal,
        volume: Double
    ): Result<String> {
        require(volume > 0.0) { "Wolumen TP musi być dodatni" }
        val side = if (proposal.side == TradeSide.BUY) "sell" else "buy"
        val params = linkedMapOf(
            "ordertype" to "limit",
            "type" to side,
            "volume" to decimal(volume),
            "pair" to normalizedPair(proposal.pair),
            "price" to decimal(proposal.takeProfit),
            "cl_ord_id" to clientOrderId(proposal.id, "tp")
        )
        return transport.post("/0/private/AddOrder", params).flatMap(::parseAddOrderTxId)
    }

    suspend fun queryOrder(txid: String): Result<KrakenOrderSnapshot> {
        require(txid.isNotBlank()) { "txid nie może być pusty" }
        return transport.post(
            "/0/private/QueryOrders",
            mapOf("txid" to txid, "trades" to "false")
        ).flatMap { parseOrderSnapshot(txid, it) }
    }

    suspend fun cancelOrder(txid: String): Result<Unit> {
        require(txid.isNotBlank()) { "txid nie może być pusty" }
        return transport.post(
            "/0/private/CancelOrder",
            mapOf("txid" to txid)
        ).flatMap { raw ->
            KrakenResponse.requireSuccess(raw).map { Unit }
        }
    }

    internal fun parseAddOrderTxId(raw: String): Result<String> = runCatching {
        KrakenResponse.requireSuccess(raw).getOrThrow()
        val root = json.parseToJsonElement(raw).jsonObject
        val txids = root["result"]?.jsonObject?.get("txid")?.jsonArray
            ?: error("Brak txid w odpowiedzi AddOrder")
        txids.firstOrNull()?.jsonPrimitive?.content
            ?.takeIf { it.isNotBlank() }
            ?: error("Pusty txid w odpowiedzi AddOrder")
    }

    internal fun parseOrderSnapshot(txid: String, raw: String): Result<KrakenOrderSnapshot> = runCatching {
        KrakenResponse.requireSuccess(raw).getOrThrow()
        val root = json.parseToJsonElement(raw).jsonObject
        val order = root["result"]?.jsonObject?.get(txid)?.jsonObject
            ?: error("Brak zlecenia $txid w odpowiedzi QueryOrders")
        KrakenOrderSnapshot(
            txid = txid,
            status = parseStatus(order["status"]?.jsonPrimitive?.content),
            volume = order["vol"]?.jsonPrimitive?.content?.toDoubleOrNull() ?: 0.0,
            executedVolume = order["vol_exec"]?.jsonPrimitive?.content?.toDoubleOrNull() ?: 0.0,
            averagePrice = order["price"]?.jsonPrimitive?.content?.toDoubleOrNull()
        )
    }

    private suspend fun addEntry(
        proposal: ExecutableProposal,
        validateOnly: Boolean
    ): Result<String> {
        val validation = ProposalValidator.validate(proposal, RiskPolicy())
        if (validation is ValidationResult.Invalid) {
            return Result.failure(IllegalArgumentException(validation.reason))
        }
        val params = linkedMapOf(
            "ordertype" to "limit",
            "type" to proposal.side.name.lowercase(),
            "volume" to decimal(proposal.volume),
            "pair" to normalizedPair(proposal.pair),
            "price" to decimal(proposal.entry),
            "cl_ord_id" to clientOrderId(proposal.id, "entry"),
            "close[ordertype]" to "stop-loss",
            "close[price]" to decimal(proposal.stopLoss),
            "validate" to validateOnly.toString()
        )
        val response = transport.post("/0/private/AddOrder", params)
        if (validateOnly) {
            return response.flatMap { raw ->
                KrakenResponse.requireSuccess(raw).map { "validated" }
            }
        }
        return response.flatMap(::parseAddOrderTxId)
    }

    private fun parseStatus(value: String?): KrakenOrderStatus = when (value?.lowercase()) {
        "pending" -> KrakenOrderStatus.PENDING
        "open" -> KrakenOrderStatus.OPEN
        "closed" -> KrakenOrderStatus.CLOSED
        "canceled", "cancelled" -> KrakenOrderStatus.CANCELED
        "expired" -> KrakenOrderStatus.EXPIRED
        else -> KrakenOrderStatus.UNKNOWN
    }

    private fun normalizedPair(pair: String): String = pair.replace("/", "")

    private fun clientOrderId(proposalId: String, suffix: String): String {
        val safe = proposalId.filter { it.isLetterOrDigit() || it == '-' || it == '_' }
        val maxPrefix = (18 - suffix.length - 1).coerceAtLeast(1)
        return safe.take(maxPrefix) + "-" + suffix
    }

    private fun decimal(value: Double): String =
        java.math.BigDecimal.valueOf(value).stripTrailingZeros().toPlainString()

    private inline fun <T, R> Result<T>.flatMap(transform: (T) -> Result<R>): Result<R> =
        fold(onSuccess = transform, onFailure = { Result.failure(it) })
}
