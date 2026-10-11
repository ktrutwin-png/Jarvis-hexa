package com.krakentrade.mobile

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Test

class KrakenTradeExecutionApiTest {
    private val proposal = ExecutableProposal(
        id = "p1",
        pair = "XRP/EUR",
        side = TradeSide.BUY,
        entry = 2.0,
        stopLoss = 1.9,
        takeProfit = 2.2,
        volume = 100.0,
        maxRiskPct = 0.5
    )

    @Test fun validateOnlyNeverPlacesLiveEntry() = runBlocking {
        var liveEntries = 0
        val gateway = object : KrakenOrderGateway {
            override suspend fun validateEntryWithStopLoss(proposal: ExecutableProposal) = Result.success("validated")
            override suspend fun placeEntryWithStopLoss(proposal: ExecutableProposal): Result<String> {
                liveEntries++
                return Result.success("entry-1")
            }
            override suspend fun placeTakeProfit(proposal: ExecutableProposal, volume: Double) = Result.success("tp")
            override suspend fun queryOrder(txid: String) =
                Result.success(KrakenOrderSnapshot(txid, KrakenOrderStatus.OPEN, 1.0, 0.0, null))
            override suspend fun cancelOrder(txid: String) = Result.success(Unit)
        }

        val api = KrakenTradeExecutionApi(
            BracketExecutionCoordinator(gateway),
            ExecutionMode.VALIDATE_ONLY
        )
        assertEquals("validated:p1", api.placeEntryWithProtection(proposal).getOrThrow())
        assertEquals(0, liveEntries)
    }

    @Test fun liveModePreflightsBeforePlacingEntry() = runBlocking {
        val calls = mutableListOf<String>()
        val gateway = object : KrakenOrderGateway {
            override suspend fun validateEntryWithStopLoss(proposal: ExecutableProposal): Result<String> {
                calls += "validate"
                return Result.success("validated")
            }
            override suspend fun placeEntryWithStopLoss(proposal: ExecutableProposal): Result<String> {
                calls += "live"
                return Result.success("entry-1")
            }
            override suspend fun placeTakeProfit(proposal: ExecutableProposal, volume: Double) = Result.success("tp")
            override suspend fun queryOrder(txid: String) =
                Result.success(KrakenOrderSnapshot(txid, KrakenOrderStatus.OPEN, 1.0, 0.0, null))
            override suspend fun cancelOrder(txid: String) = Result.success(Unit)
        }

        val result = KrakenTradeExecutionApi(
            BracketExecutionCoordinator(gateway),
            ExecutionMode.LIVE
        ).placeEntryWithProtection(proposal)

        assertEquals("entry-1", result.getOrThrow())
        assertEquals(listOf("validate", "live"), calls)
    }
}
