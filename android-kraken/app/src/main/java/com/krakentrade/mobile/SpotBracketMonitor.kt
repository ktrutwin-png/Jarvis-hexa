package com.krakentrade.mobile

data class ArmedBracket(
    val entryTxid: String,
    val stopLossTxid: String,
    val takeProfitTxid: String
)

sealed interface BracketReconcileResult {
    data class Active(
        val stopLossStatus: KrakenOrderStatus,
        val takeProfitStatus: KrakenOrderStatus
    ) : BracketReconcileResult

    data class ExitedByStopLoss(val canceledTakeProfit: Boolean) : BracketReconcileResult
    data class ExitedByTakeProfit(val canceledStopLoss: Boolean) : BracketReconcileResult
    data class Failed(val reason: String) : BracketReconcileResult
}

class SpotBracketMonitor(
    private val orders: KrakenOrderGateway,
    private val openOrders: KrakenOpenOrdersApi
) {
    suspend fun discoverAndArm(
        proposal: ExecutableProposal,
        entryTxid: String
    ): Result<ArmedBracket> {
        val entry = orders.queryOrder(entryTxid).getOrElse { return Result.failure(it) }
        if (!entry.isFilled) {
            return Result.failure(IllegalStateException("Zlecenie wejścia nie jest jeszcze w pełni wykonane"))
        }

        val stop = openOrders.findConditionalChild(entryTxid, "stop-loss")
            .getOrElse { return Result.failure(it) }
            ?: return Result.failure(
                IllegalStateException("Nie znaleziono aktywnego conditional stop-loss")
            )

        val tpTxid = orders.placeTakeProfit(proposal, entry.executedVolume)
            .getOrElse { return Result.failure(it) }

        return Result.success(
            ArmedBracket(
                entryTxid = entryTxid,
                stopLossTxid = stop.txid,
                takeProfitTxid = tpTxid
            )
        )
    }

    suspend fun reconcile(bracket: ArmedBracket): BracketReconcileResult {
        val stop = orders.queryOrder(bracket.stopLossTxid).getOrElse {
            return BracketReconcileResult.Failed(it.message ?: "Błąd odczytu stop-loss")
        }
        val tp = orders.queryOrder(bracket.takeProfitTxid).getOrElse {
            return BracketReconcileResult.Failed(it.message ?: "Błąd odczytu take-profit")
        }

        if (stop.isFilled) {
            val canceled = if (!tp.isTerminal) orders.cancelOrder(tp.txid).isSuccess else true
            return BracketReconcileResult.ExitedByStopLoss(canceled)
        }

        if (tp.isFilled) {
            val canceled = if (!stop.isTerminal) orders.cancelOrder(stop.txid).isSuccess else true
            return BracketReconcileResult.ExitedByTakeProfit(canceled)
        }

        return BracketReconcileResult.Active(
            stopLossStatus = stop.status,
            takeProfitStatus = tp.status
        )
    }
}
