package com.krakentrade.mobile

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URI
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

class KrakenPrivateTransport(
    private val credentialsProvider: () -> KrakenCredentials,
    private val nonce: KrakenNonce = KrakenNonce(),
    private val baseUrl: String = "https://api.kraken.com"
) {
    suspend fun post(
        uriPath: String,
        parameters: Map<String, String>
    ): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val credentials = credentialsProvider()
            require(!CredentialPolicy.isPlaceholder(credentials.apiKey)) { "Brak klucza API" }
            require(!CredentialPolicy.isPlaceholder(credentials.apiSecretBase64)) { "Brak sekretu API" }

            val nonceValue = nonce.next()
            val bodyParameters = linkedMapOf<String, String>()
            bodyParameters["nonce"] = nonceValue
            bodyParameters.putAll(parameters)
            val body = formEncode(bodyParameters)
            val signature = KrakenAuthSigner.sign(uriPath, nonceValue, body, credentials.apiSecretBase64)

            val connection = URI.create(baseUrl + uriPath).toURL().openConnection() as HttpURLConnection
            try {
                connection.requestMethod = "POST"
                connection.connectTimeout = 15_000
                connection.readTimeout = 20_000
                connection.doOutput = true
                connection.setRequestProperty("API-Key", credentials.apiKey)
                connection.setRequestProperty("API-Sign", signature)
                connection.setRequestProperty("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
                connection.outputStream.use { out ->
                    out.write(body.toByteArray(StandardCharsets.UTF_8))
                }

                val status = connection.responseCode
                val stream = if (status in 200..299) connection.inputStream else connection.errorStream
                val response = stream?.use { input ->
                    BufferedReader(InputStreamReader(input, StandardCharsets.UTF_8)).readText()
                }.orEmpty()

                if (status !in 200..299) {
                    error("Kraken HTTP $status: $response")
                }
                response
            } finally {
                connection.disconnect()
            }
        }
    }

    private fun formEncode(values: Map<String, String>): String =
        values.entries.joinToString("&") { (key, value) ->
            URLEncoder.encode(key, StandardCharsets.UTF_8.name()) + "=" +
                URLEncoder.encode(value, StandardCharsets.UTF_8.name())
        }
}
