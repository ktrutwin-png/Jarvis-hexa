package com.krakentrade.mobile

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class KrakenOpenOrdersApiTest {
    private val api = KrakenOpenOrdersApi(
        KrakenPrivateTransport(
            credentialsProvider = { KrakenCredentials("key", "eA==") }
        )
    )

    @Test fun parsesReferralOrderIdForConditionalChild() {
        val raw = """{
          "error": [],
          "result": {
            "open": {
              "OSTOP1": {
                "refid": "OENTRY1",
                "status": "open",
                "cl_ord_id": "p1-sl",
                "descr": {"pair":"XRPEUR","type":"sell","ordertype":"stop-loss"},
                "vol":"100.0",
                "vol_exec":"0.0"
              }
            }
          }
        }"""
        val order = api.parseOpenOrders(raw).getOrThrow().single()
        assertEquals("OENTRY1", order.refid)
        assertEquals("stop-loss", order.orderType)
    }

    @Test fun noneReferralBecomesNull() {
        val raw = """{
          "error": [],
          "result": {
            "open": {
              "O1": {
                "refid": "None",
                "status": "open",
                "descr": {"pair":"XRPEUR","type":"buy","ordertype":"limit"},
                "vol":"1",
                "vol_exec":"0"
              }
            }
          }
        }"""
        assertNull(api.parseOpenOrders(raw).getOrThrow().single().refid)
    }
}
