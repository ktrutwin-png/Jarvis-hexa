package com.krakentrade.mobile

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class KrakenReadinessTest {
    @Test fun analysisRequiresCredentialsAndFundsPermission() {
        assertFalse(
            KrakenReadiness(
                credentialsPresent = true,
                canQueryFunds = false,
                canQueryOrders = true,
                canModifyTrades = true,
                canCloseTrades = true
            ).readyForAnalysis
        )
        assertTrue(
            KrakenReadiness(
                credentialsPresent = true,
                canQueryFunds = true,
                canQueryOrders = false,
                canModifyTrades = false,
                canCloseTrades = false
            ).readyForAnalysis
        )
    }

    @Test fun validationRequiresModifyTradePermission() {
        assertTrue(
            KrakenReadiness(
                credentialsPresent = true,
                canQueryFunds = true,
                canQueryOrders = true,
                canModifyTrades = true,
                canCloseTrades = false
            ).readyForOrderValidation
        )
    }
}
