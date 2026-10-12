package com.krakentrade.mobile

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PairOrderRulesTest {
    private val rules = PairRules(
        internalId = "XXRPZEUR",
        altName = "XRPEUR",
        displayName = "XRP/EUR",
        baseAsset = "XXRP",
        quoteAsset = "ZEUR",
        orderMin = 1.0,
        costMin = 0.5,
        tickSize = 0.0001,
        pairDecimals = 4,
        lotDecimals = 2,
        status = "online"
    )

    @Test fun normalizesPriceAndVolumeToExchangePrecision() {
        val p = ExecutableProposal(
            "p1", "XRP/EUR", TradeSide.BUY,
            2.00004, 1.90004, 2.20004, 10.129, 0.5
        )
        val n = PairOrderRules.normalize(p, rules).getOrThrow()
        assertEquals("2.0000", n.entry)
        assertEquals("10.12", n.volume)
    }

    @Test fun rejectsBelowMinimumOrder() {
        val p = ExecutableProposal(
            "p1", "XRP/EUR", TradeSide.BUY,
            2.0, 1.9, 2.2, 0.5, 0.5
        )
        assertTrue(PairOrderRules.normalize(p, rules).isFailure)
    }
}
