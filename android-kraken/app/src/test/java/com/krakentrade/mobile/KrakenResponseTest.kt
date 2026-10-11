package com.krakentrade.mobile

import org.junit.Assert.assertTrue
import org.junit.Test

class KrakenResponseTest {
    @Test fun successEnvelopePasses() {
        val raw = """{"error":[],"result":{"descr":{"order":"buy"}}}"""
        assertTrue(KrakenResponse.requireSuccess(raw).isSuccess)
    }

    @Test fun apiErrorsFail() {
        val raw = """{"error":["EOrder:Insufficient funds"],"result":{}}"""
        val result = KrakenResponse.requireSuccess(raw)
        assertTrue(result.isFailure)
        assertTrue(result.exceptionOrNull()?.message?.contains("Insufficient funds") == true)
    }
}
