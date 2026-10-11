package com.krakentrade.mobile

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SpotBracketMonitorTest {
    private val proposal = ExecutableProposal(
        "p1", "XRP/EUR", TradeSide.BUY, 2.0, 1.9, 2.2, 100.0, 0.5
    )

    @Test fun discoverArmsTakeProfitOnlyAfterFindingStopChild() = runBlocking {
        var tpCalls = 0
        val orders = object : KrakenOrderGateway {
            override suspend fun validateEntryWithStopLoss(proposal: ExecutableProposal) = Result.success("validated")
            override suspend fun placeEntryWithStopLoss(proposal: ExecutableProposal) = Result.success("entry")
            override suspend fun placeTakeProfit(proposal: ExecutableProposal, volume: Double): Result<String> {
                tpCalls++
                return Result.success("tp")
            }
            override suspend fun queryOrder(txid: String) =
                Result.success(KrakenOrderSnapshot(txid, KrakenOrderStatus.CLOSED, 100.0, 100.0, 2.0))
            override suspend fun cancelOrder(txid: String) = Result.success(Unit)
        }
        val open = object : OpenOrdersGateway {
            override suspend fun listOpenOrders() = Result.success(emptyList<KrakenOpenOrder>())
            override suspend fun findConditionalChild(entryTxid: String, orderType: String) =
                Result.success(KrakenOpenOrder(
                    txid = "sl",
                    refid = entryTxid,
                    clientOrderId = null,
                    status = KrakenOrderStatus.OPEN,
                    orderType = "stop-loss",
                    side = "sell",
                    volume = 100.0,
                    executedVolume = 0.0
                ))
        }

        val armed = SpotBracketMonitor(orders, open).discoverAndArm(proposal, "entry").getOrThrow()
        assertEquals("sl", armed.stopLossTxid)
        assertEquals("tp", armed.takeProfitTxid)
        assertEquals(1, tpCalls)
    }

    @Test fun takeProfitFillCancelsStopLoss() = runBlocking {
        val canceled = mutableListOf<String>()
        val orders = object : KrakenOrderGateway {
            override suspend fun validateEntryWithStopLoss(proposal: ExecutableProposal) = Result.success("validated")
            override suspend fun placeEntryWithStopLoss(proposal: ExecutableProposal) = Result.success("entry")
            override suspend fun placeTakeProfit(proposal: ExecutableProposal, volume: Double) = Result.success("tp")
            override suspend fun queryOrder(txid: String): Result<KrakenOrderSnapshot> =
                if (txid == "tp") Result.success(KrakenOrderSnapshot("tp", KrakenOrderStatus.CLOSED, 100.0, 100.0, 2.2))
                else Result.success(KrakenOrderSnapshot("sl", KrakenOrderStatus.OPEN, 100.0, 0.0, null))
            override suspend fun cancelOrder(txid: String): Result<Unit> {
                canceled += txid
                return Result.success(Unit)
            }
        }
        val open = object : OpenOrdersGateway {
            override suspend fun listOpenOrders() = Result.success(emptyList<KrakenOpenOrder>())
            override suspend fun findConditionalChild(entryTxid: String, orderType: String) = Result.success(null)
        }

        val result = SpotBracketMonitor(orders, open).reconcile(
            ArmedBracket("entry", "sl", "tp")
        )
        assertTrue(result is BracketReconcileResult.ExitedByTakeProfit)
        assertEquals(listOf("sl"), canceled)
    }
}
