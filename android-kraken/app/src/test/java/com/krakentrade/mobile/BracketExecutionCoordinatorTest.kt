package com.krakentrade.mobile

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class BracketExecutionCoordinatorTest {
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

    @Test fun takeProfitIsNotPlacedBeforeEntryFill() = runBlocking {
        var takeProfitCalls = 0
        val gateway = fakeGateway(
            snapshot = KrakenOrderSnapshot("entry-1", KrakenOrderStatus.OPEN, 100.0, 20.0, 2.0),
            onTakeProfit = { takeProfitCalls++; Result.success("tp-1") }
        )
        val state = BracketExecutionCoordinator(gateway)
            .armTakeProfitAfterFill(proposal, "entry-1")
            .getOrThrow()

        assertTrue(state is BracketState.WaitingForEntryFill)
        assertEquals(0, takeProfitCalls)
    }

    @Test fun takeProfitUsesExecutedVolumeAfterFill() = runBlocking {
        var submittedVolume = 0.0
        val gateway = fakeGateway(
            snapshot = KrakenOrderSnapshot("entry-1", KrakenOrderStatus.CLOSED, 100.0, 100.0, 2.01),
            onTakeProfit = { volume -> submittedVolume = volume; Result.success("tp-1") }
        )
        val state = BracketExecutionCoordinator(gateway)
            .armTakeProfitAfterFill(proposal, "entry-1")
            .getOrThrow()

        assertTrue(state is BracketState.Protected)
        assertEquals(100.0, submittedVolume, 0.000001)
    }

    private fun fakeGateway(
        snapshot: KrakenOrderSnapshot,
        onTakeProfit: (Double) -> Result<String>
    ) = object : KrakenOrderGateway {
        override suspend fun validateEntryWithStopLoss(proposal: ExecutableProposal) = Result.success("validated")
        override suspend fun placeEntryWithStopLoss(proposal: ExecutableProposal) = Result.success("entry-1")
        override suspend fun placeTakeProfit(proposal: ExecutableProposal, volume: Double) = onTakeProfit(volume)
        override suspend fun queryOrder(txid: String) = Result.success(snapshot)
        override suspend fun cancelOrder(txid: String) = Result.success(Unit)
    }
}
