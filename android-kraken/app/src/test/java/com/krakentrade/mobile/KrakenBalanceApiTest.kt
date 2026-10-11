package com.krakentrade.mobile

import org.junit.Assert.assertEquals
import org.junit.Test

class KrakenBalanceApiTest {
    private val api = KrakenBalanceApi(
        KrakenPrivateTransport(
            credentialsProvider = { KrakenCredentials("key", "eA==") }
        )
    )

    @Test fun parsesBalanceMap() {
        val balances = api.parseBalances(
            """{"error":[],"result":{"ZEUR":"500.25","XXRP":"200.0"}}"""
        ).getOrThrow()
        assertEquals(500.25, balances["ZEUR"] ?: 0.0, 0.000001)
        assertEquals(200.0, balances["XXRP"] ?: 0.0, 0.000001)
    }

    @Test fun buildsPairCapacityWithoutCountingUnrelatedAssets() {
        val rules = PairRules(
            internalId = "XXRPZEUR",
            altName = "XRPEUR",
            displayName = "XRP/EUR",
            baseAsset = "XXRP",
            quoteAsset = "ZEUR",
            orderMin = 1.0,
            costMin = 0.5,
            tickSize = 0.00001,
            pairDecimals = 5,
            lotDecimals = 8,
            status = "online"
        )
        val capacity = api.capacityForPair(
            rules,
            mapOf("ZEUR" to 500.0, "XXRP" to 200.0, "XXBT" to 99.0),
            lastPrice = 2.0
        )
        assertEquals(500.0, capacity.quoteBalance, 0.000001)
        assertEquals(200.0, capacity.baseBalance, 0.000001)
        assertEquals(900.0, capacity.accountEquityQuote, 0.000001)
    }
}
