package com.krakentrade.mobile

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TradeSessionTest {
    private val proposal = ExecutableProposal(
        "p1", "XRP/EUR", TradeSide.BUY, 2.0, 1.9, 2.2, 100.0, 0.5
    )

    @Test fun approvalIsRequiredAndConsumedByExecutor() = runBlocking {
        var calls = 0
        val gate = ApprovalGate()
        val api = object : KrakenPrivateApi {
            override suspend fun placeEntryWithProtection(proposal: ExecutableProposal): Result<String> {
                calls++
                return Result.success("order-1")
            }
        }
        val session = TradeSession(TradeExecutor(api, gate), gate)
        session.present(proposal)

        val result = session.approveAndExecute()
        assertEquals("order-1", result.getOrThrow())
        assertEquals(1, calls)
        assertTrue(session.state is TradeState.ProtectedOpen)
    }
}
