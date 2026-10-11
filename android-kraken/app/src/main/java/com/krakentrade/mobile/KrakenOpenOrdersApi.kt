package com.krakentrade.mobile

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

data class KrakenOpenOrder(
    val txid: String,
    val refid: String?,
    val clientOrderId: String?,
    val status: KrakenOrderStatus,
    val orderType: String,
    val side: String,
    val volume: Double,
    val executedVolume: Double
)

interface OpenOrdersGateway {
    override suspend fun listOpenOrders(): Result<List<KrakenOpenOrder>>
    override suspend fun findConditionalChild(entryTxid: String, orderType: String): Result<KrakenOpenOrder?>
}

class KrakenOpenOrdersApi(
    private val transport: KrakenPrivateTransport
) : OpenOrdersGateway {
    private val json = Json { ignoreUnknownKeys = true }

    suspend fun listOpenOrders(): Result<List<KrakenOpenOrder>> =
        transport.post(
            "/0/private/OpenOrders",
            mapOf("trades" to "false")
        ).flatMap(::parseOpenOrders)

    suspend fun findConditionalChild(
        entryTxid: String,
        orderType: String
    ): Result<KrakenOpenOrder?> =
        listOpenOrders().map { orders ->
            orders.firstOrNull { order ->
                order.refid == entryTxid &&
                    order.orderType.equals(orderType, ignoreCase = true)
            }
        }

    internal fun parseOpenOrders(raw: String): Result<List<KrakenOpenOrder>> = runCatching {
        KrakenResponse.requireSuccess(raw).getOrThrow()
        val root = json.parseToJsonElement(raw).jsonObject
        val open = root["result"]?.jsonObject?.get("open")?.jsonObject ?: return@runCatching emptyList()

        open.map { (txid, element) ->
            val order = element.jsonObject
            val descr = order["descr"]?.jsonObject ?: error("Brak descr dla $txid")
            KrakenOpenOrder(
                txid = txid,
                refid = order["refid"]?.jsonPrimitive?.content?.takeUnless {
                    it.equals("none", ignoreCase = true) || it == "null"
                },
                clientOrderId = order["cl_ord_id"]?.jsonPrimitive?.content,
                status = when (order["status"]?.jsonPrimitive?.content?.lowercase()) {
                    "pending" -> KrakenOrderStatus.PENDING
                    "open" -> KrakenOrderStatus.OPEN
                    "closed" -> KrakenOrderStatus.CLOSED
                    "canceled", "cancelled" -> KrakenOrderStatus.CANCELED
                    "expired" -> KrakenOrderStatus.EXPIRED
                    else -> KrakenOrderStatus.UNKNOWN
                },
                orderType = descr["ordertype"]?.jsonPrimitive?.content.orEmpty(),
                side = descr["type"]?.jsonPrimitive?.content.orEmpty(),
                volume = order["vol"]?.jsonPrimitive?.content?.toDoubleOrNull() ?: 0.0,
                executedVolume = order["vol_exec"]?.jsonPrimitive?.content?.toDoubleOrNull() ?: 0.0
            )
        }
    }

    private inline fun <T, R> Result<T>.flatMap(transform: (T) -> Result<R>): Result<R> =
        fold(onSuccess = transform, onFailure = { Result.failure(it) })
}
