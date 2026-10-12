package com.krakentrade.mobile

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class KrakenOrderApiTest {
    private fun api() = KrakenOrderApi(
        KrakenPrivateTransport(
            credentialsProvider = { KrakenCredentials("key", "eA==") }
        )
    )

    @Test fun parsesAddOrderTxid() {
        val raw = """{"error":[],"result":{"descr":{"order":"buy"},"txid":["OUF4EM-FRGI2-MQMWZD"]}}"""
        assertEquals("OUF4EM-FRGI2-MQMWZD", api().parseAddOrderTxId(raw).getOrThrow())
    }

    @Test fun parsesClosedFilledOrder() {
        val raw = """{
          "error": [],
          "result": {
            "OUF4EM-FRGI2-MQMWZD": {
              "status": "closed",
              "vol": "100.0",
              "vol_exec": "100.0",
              "price": "2.01"
            }
          }
        }"""
        val snapshot = api().parseOrderSnapshot("OUF4EM-FRGI2-MQMWZD", raw).getOrThrow()
        assertEquals(KrakenOrderStatus.CLOSED, snapshot.status)
        assertTrue(snapshot.isFilled)
        assertEquals(100.0, snapshot.executedVolume, 0.000001)
    }
}
