package com.krakentrade.mobile

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

data class KrakenApiKeyStatus(
    val name: String?,
    val permissions: Set<String>,
    val validUntil: String?,
    val ipAllowlist: List<String>
) {
    val canModifyTrades: Boolean
        get() = "modify-trades" in permissions
}

class KrakenAccountApi(
    private val transport: KrakenPrivateTransport
) {
    suspend fun getApiKeyStatus(): Result<KrakenApiKeyStatus> =
        transport.post("/0/private/GetApiKeyInfo", emptyMap()).fold(
            onSuccess = { parseKeyInfo(it) },
            onFailure = { Result.failure(it) }
        )

    internal fun parseKeyInfo(raw: String): Result<KrakenApiKeyStatus> = runCatching {
        KrakenResponse.requireSuccess(raw).getOrThrow()
        val root = Json.parseToJsonElement(raw).jsonObject
        val result = root["result"]?.jsonObject ?: error("Brak result w odpowiedzi GetApiKeyInfo")
        val permissions = result["permissions"]?.jsonArray
            ?.map { it.jsonPrimitive.content }
            ?.toSet()
            .orEmpty()
        val ipAllowlist = result["ipAllowlist"]?.jsonArray
            ?.map { it.jsonPrimitive.content }
            .orEmpty()
        KrakenApiKeyStatus(
            name = result["apiKeyName"]?.jsonPrimitive?.content,
            permissions = permissions,
            validUntil = result["validUntil"]?.jsonPrimitive?.content,
            ipAllowlist = ipAllowlist
        )
    }
}
