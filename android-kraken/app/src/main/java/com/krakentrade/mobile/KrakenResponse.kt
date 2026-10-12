package com.krakentrade.mobile

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

object KrakenResponse {
    private val json = Json { ignoreUnknownKeys = true }

    fun requireSuccess(raw: String): Result<String> = runCatching {
        val root = json.parseToJsonElement(raw).jsonObject
        val errors = root["error"]?.jsonArray
            ?.mapNotNull { element -> element.jsonPrimitive.content.takeIf { it.isNotBlank() } }
            .orEmpty()
        if (errors.isNotEmpty()) error(errors.joinToString("; "))
        raw
    }
}
