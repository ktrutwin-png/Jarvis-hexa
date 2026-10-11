package com.krakentrade.mobile

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TradingAnalysisServiceTest {
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
        lotDecimals = 4,
        status = "online"
    )

    @Test fun completeAnalysisBuildsNormalizedTradeProposal() = runBlocking {
        val candles = (0 until 40).map { i ->
            val close = 1.50 + i * 0.01
            Candle(
                timeEpochSeconds = i.toLong(),
                open = close - 0.005,
                high = close + 0.02,
                low = close - 0.02,
                close = close,
                vwap = close,
                volume = 1000.0,
                tradeCount = 20
            )
        }

        val service = TradingAnalysisService(
            market = object : MarketDataGateway {
                override suspend fun fetchOhlc(pair: String, intervalMinutes: Int) = Result.success(candles)
            },
            pairs = object : PairRulesGateway {
                override suspend fun fetchPair(pair: String) = Result.success(rules)
            },
            balances = object : BalanceGateway {
                override suspend fun fetchBalances() =
                    Result.success(mapOf("ZEUR" to 1000.0, "XXRP" to 0.0))
            }
        )

        val result = service.analyze(
            pair = "XRP/EUR",
            intervalMinutes = 5,
            proposalId = "analysis-1"
        ).getOrThrow()

        assertTrue(result is ProposalDecision.Trade)
        val proposal = (result as ProposalDecision.Trade).proposal
        assertEquals("XRP/EUR", proposal.pair)
        assertEquals(TradeSide.BUY, proposal.side)
        assertTrue(proposal.volume > 0.0)
    }

    @Test fun pairOfflineStopsBeforeProposal() = runBlocking {
        val offline = rules.copy(status = "cancel_only")
        var marketCalls = 0
        val service = TradingAnalysisService(
            market = object : MarketDataGateway {
                override suspend fun fetchOhlc(pair: String, intervalMinutes: Int): Result<List<Candle>> {
                    marketCalls++
                    return Result.success(emptyList())
                }
            },
            pairs = object : PairRulesGateway {
                override suspend fun fetchPair(pair: String) = Result.success(offline)
            },
            balances = object : BalanceGateway {
                override suspend fun fetchBalances() = Result.success(emptyMap())
            }
        )

        assertTrue(service.analyze("XRP/EUR", proposalId = "p").isFailure)
        assertEquals(0, marketCalls)
    }
}
