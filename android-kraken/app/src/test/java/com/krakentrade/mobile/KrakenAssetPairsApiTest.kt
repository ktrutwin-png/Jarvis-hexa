package com.krakentrade.mobile

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class KrakenAssetPairsApiTest {
    @Test fun parsesPairRules() {
        val raw = """{
          "error": [],
          "result": {
            "XXRPZEUR": {
              "altname": "XRPEUR",
              "wsname": "XRP/EUR",
              "base": "XXRP",
              "quote": "ZEUR",
              "pair_decimals": 5,
              "lot_decimals": 8,
              "ordermin": "1.0",
              "costmin": "0.5",
              "tick_size": "0.00001",
              "status": "online"
            }
          }
        }"""
        val rules = KrakenAssetPairsApi().parseSinglePair(raw)
        assertEquals("XRP/EUR", rules.displayName)
        assertEquals("XXRP", rules.baseAsset)
        assertEquals("ZEUR", rules.quoteAsset)
        assertTrue(rules.isOnline)
        assertEquals(1.0, rules.orderMin, 0.000001)
    }
}
