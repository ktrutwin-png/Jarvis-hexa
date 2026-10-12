package com.krakentrade.mobile

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ProposalEngineTest {
    @Test fun upTrendBuildsBuyWithRiskSizedVolume() {
        val decision = ProposalEngine.build(
            pair = "XRP/EUR",
            indicators = MarketIndicators(2.0, 2.02, 1.98, 0.05),
            capacity = AccountCapacity(
                quoteBalance = 1000.0,
                baseBalance = 0.0,
                accountEquityQuote = 1000.0
            ),
            config = StrategyConfig(
                riskPct = 0.5,
                atrStopMultiplier = 1.0,
                rewardRiskRatio = 2.0,
                maxVolume = 1000.0
            ),
            proposalId = "p1"
        )
        val proposal = (decision as ProposalDecision.Trade).proposal
        assertEquals(TradeSide.BUY, proposal.side)
        assertEquals(100.0, proposal.volume, 0.000001)
        assertEquals(1.95, proposal.stopLoss, 0.000001)
        assertEquals(2.10, proposal.takeProfit, 0.000001)
    }

    @Test fun downTrendDoesNotCreateNakedSpotShort() {
        val decision = ProposalEngine.build(
            pair = "XRP/EUR",
            indicators = MarketIndicators(2.0, 1.98, 2.02, 0.05),
            capacity = AccountCapacity(
                quoteBalance = 1000.0,
                baseBalance = 0.0,
                accountEquityQuote = 1000.0
            ),
            proposalId = "p2"
        )
        assertTrue(decision is ProposalDecision.Wait)
    }

    @Test fun sellVolumeNeverExceedsHeldBaseAsset() {
        val decision = ProposalEngine.build(
            pair = "XRP/EUR",
            indicators = MarketIndicators(2.0, 1.98, 2.02, 0.05),
            capacity = AccountCapacity(
                quoteBalance = 0.0,
                baseBalance = 25.0,
                accountEquityQuote = 1000.0
            ),
            proposalId = "p3"
        )
        val proposal = (decision as ProposalDecision.Trade).proposal
        assertEquals(TradeSide.SELL, proposal.side)
        assertTrue(proposal.volume <= 25.0)
    }
}
