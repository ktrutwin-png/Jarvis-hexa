package com.krakentrade.mobile

import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.util.Base64
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

data class KrakenCredentials(
    val apiKey: String,
    val apiSecretBase64: String
)

object KrakenAuthSigner {
    fun sign(
        uriPath: String,
        nonce: String,
        encodedPayload: String,
        apiSecretBase64: String
    ): String {
        require(uriPath.startsWith("/0/private/")) { "Private Kraken URI path required" }
        val sha256 = MessageDigest.getInstance("SHA-256")
        val payloadDigest = sha256.digest((nonce + encodedPayload).toByteArray(StandardCharsets.UTF_8))
        val message = uriPath.toByteArray(StandardCharsets.UTF_8) + payloadDigest
        val secret = Base64.getDecoder().decode(apiSecretBase64)
        val mac = Mac.getInstance("HmacSHA512")
        mac.init(SecretKeySpec(secret, "HmacSHA512"))
        return Base64.getEncoder().encodeToString(mac.doFinal(message))
    }
}
