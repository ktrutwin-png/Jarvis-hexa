package com.krakentrade.mobile

/**
 * API secrets must never be embedded in source, logs or proposal objects.
 * Production storage must use Android Keystore-backed encryption.
 */
object CredentialPolicy {
    const val API_KEY_ALIAS = "kraken_api_key"
    const val API_SECRET_ALIAS = "kraken_api_secret"
    fun isPlaceholder(value: String?): Boolean =
        value.isNullOrBlank() || value.startsWith("CHANGE_ME")
}
