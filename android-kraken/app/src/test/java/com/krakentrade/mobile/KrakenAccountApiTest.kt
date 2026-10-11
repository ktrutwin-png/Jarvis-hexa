package com.krakentrade.mobile

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class KrakenAccountApiTest {
    @Test fun parsesTradingPermission() {
        val raw = """{
          "error": [],
          "result": {
            "apiKeyName": "phone-app",
            "permissions": ["query-funds","query-open-trades","modify-trades"],
            "validUntil": "0",
            "ipAllowlist": []
          }
        }"""
        val status = KrakenAccountApi(
            KrakenPrivateTransport(
                credentialsProvider = { KrakenCredentials("x", "eA==") }
            )
        ).parseKeyInfo(raw).getOrThrow()
        assertTrue(status.canModifyTrades)
        assertFalse(status.permissions.contains("withdraw-funds"))
    }
}
