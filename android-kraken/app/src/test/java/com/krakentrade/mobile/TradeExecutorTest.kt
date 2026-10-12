package com.krakentrade.mobile

import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class TradeExecutorTest {
    private val proposal = ExecutableProposal("p1","XRP/EUR",TradeSide.BUY,2.0,1.9,2.2,100.0,0.5)

    @Test fun cannotExecuteWithoutApproval() = runBlocking {
        val api = object : KrakenPrivateApi {
            override suspend fun placeEntryWithProtection(proposal: ExecutableProposal) = Result.success("order")
        }
        val result = TradeExecutor(api, ApprovalGate()).execute(proposal)
        assertTrue(result.isFailure)
        assertTrue(result.exceptionOrNull() is SecurityException)
    }

    @Test fun approvedProposalExecutesOnlyOnce() = runBlocking {
        var calls = 0
        val api = object : KrakenPrivateApi {
            override suspend fun placeEntryWithProtection(proposal: ExecutableProposal): Result<String> {
                calls++
                return Result.success("order-1")
            }
        }
        val gate = ApprovalGate().also { it.approve("p1") }
        val executor = TradeExecutor(api, gate)
        assertEquals("order-1", executor.execute(proposal).getOrNull())
        assertTrue(executor.execute(proposal).isFailure)
        assertEquals(1, calls)
    }
}
