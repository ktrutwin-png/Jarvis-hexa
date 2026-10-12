package com.krakentrade.mobile

import org.junit.Assert.assertTrue
import org.junit.Test

class KrakenNonceTest {
    @Test fun nonceIsStrictlyIncreasing() {
        val nonce = KrakenNonce(1)
        val values = List(100) { nonce.next().toLong() }
        assertTrue(values.zipWithNext().all { (a, b) -> b > a })
    }
}
