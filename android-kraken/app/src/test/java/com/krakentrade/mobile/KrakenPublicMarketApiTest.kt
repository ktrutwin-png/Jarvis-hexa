package com.krakentrade.mobile

import org.junit.Assert.assertEquals
import org.junit.Test

class KrakenPublicMarketApiTest {
    @Test fun parserDropsCurrentUncommittedCandle() {
        val raw = """{
          "error": [],
          "result": {
            "XRP/EUR": [
              [1000,"1.0","1.2","0.9","1.1","1.05","100",10],
              [1060,"1.1","1.3","1.0","1.2","1.15","120",12]
            ],
            "last": 1060
          }
        }"""
        val candles = KrakenPublicMarketApi().parseOhlc(raw)
        assertEquals(1, candles.size)
        assertEquals(1.1, candles.single().close, 0.000001)
    }
}
