package com.krakentrade.mobile

/**
 * Coordinates a spot bracket in two phases:
 * 1. entry order is created with a Kraken conditional stop-loss,
 * 2. take-profit is armed only after the entry is confirmed filled.
 *
 * Live execution remains caller-controlled; this coordinator never creates an entry
 * without an approval already consumed by TradeExecutor.
 */
class BracketExecutionCoordinator(
    private val orders: KrakenOrderGateway
) {
    suspend fun preflight(proposal: ExecutableProposal): Result<Unit> =
        orders.validateEntryWithStopLoss(proposal).map { Unit }

    suspend fun placeEntry(proposal: ExecutableProposal): Result<String> =
        orders.placeEntryWithStopLoss(proposal)

    suspend fun armTakeProfitAfterFill(
        proposal: ExecutableProposal,
        entryTxid: String
    ): Result<BracketState> {
        val snapshot = orders.queryOrder(entryTxid).getOrElse {
            return Result.failure(it)
        }
        if (!snapshot.isFilled) {
            return Result.success(
                BracketState.WaitingForEntryFill(
                    entryTxid = entryTxid,
                    status = snapshot.status,
                    executedVolume = snapshot.executedVolume
                )
            )
        }
        val tpTxid = orders.placeTakeProfit(proposal, snapshot.executedVolume).getOrElse {
            return Result.failure(it)
        }
        return Result.success(
            BracketState.Protected(
                entryTxid = entryTxid,
                takeProfitTxid = tpTxid,
                filledVolume = snapshot.executedVolume
            )
        )
    }
}

sealed interface BracketState {
    data class WaitingForEntryFill(
        val entryTxid: String,
        val status: KrakenOrderStatus,
        val executedVolume: Double
    ) : BracketState

    data class Protected(
        val entryTxid: String,
        val takeProfitTxid: String,
        val filledVolume: Double
    ) : BracketState
}
